# Skelril Deployment - Deployment script
# Copyright (C) 2015 Wyatt Childers
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Based in part on code Copyright (C) 2003-2007
# Robey Pointer <robeypointer@gmail.com> provided in paramiko.

import json
import socket
import sys
import os
import re
import shutil
import paramiko
import traceback
from getpass import getpass
from operator import itemgetter, attrgetter
from paramiko import SFTPClient
from paramiko.ssh_exception import AuthenticationException

# Used for the destination declarations

class Destination:
    def __init__(self, id):
        self.id = id

    def getIdentifierStr(self):
        return "[" + self.id + "]"

class RemoteDestination(Destination):
    def __init__(self, id, user, addr):
        super().__init__(id)
        self.user = user
        self.addr = addr
        self.password = None
        self.deriveRemoteDetails()

    def deriveRemoteDetails(self):
        hostname = self.addr
        port = 22

        if hostname.find(':') >= 0:
            hostname, portstr = hostname.split(':')
            port = int(portstr)

        self.hostname = hostname
        self.port = port

    def getIdentifierStr(self):
        return "[" + self.id + " - " + self.hostname + ":" + str(self.port) + "]"

class LocalDestination(Destination):
    def __init__(self):
        super().__init__("local")

class DestDecl:
    def __init__(self, id, dir):
        self.id = id
        self.dir = dir

class Source:
    def __init__(self, id, dir):
        self.id = id
        self.dir = dir

class FileSource(Source):
    def __init__(self, id, expr, dir):
        super().__init__(id, dir)
        self.expr = expr

class MapSource(Source):
    def __init__(self, id, dir, exclusions):
        super().__init__(id, dir)
        self.exclusions = exclusions

class Target:
    def __init__(self, id, src, destDecls):
        self.id = id
        self.src = src
        self.destDecls = destDecls

class FileTarget(Target):
    def __init__(self, id, name, src, destDecls):
        super().__init__(id, src, destDecls)
        self.name = name

    def getFiles(self):
        matchCandidates = []

        for fEntry in os.listdir(self.src.dir):
            if re.match(self.src.expr, fEntry):
                fPath = os.path.join(self.src.dir, fEntry)
                matchCandidates.append((fPath, os.path.getmtime(fPath)))

        return [sorted(matchCandidates, key = itemgetter(1), reverse = True)[0][0]]

    def send(self, destDecl, filePath):
        if self.src.id != "local":
            raise NotImplementedError("Source must be local")

        destFile = os.path.join(destDecl.dir, self.name)

        if destDecl.id == "local":
            lUpload(filePath, destFile)
        else:
            upload(destinations[destDecl.id], filePath, destFile)

class MapTarget(Target):
    def __init__(self, id, mode, src, destDecls):
        super().__init__(id, src, destDecls)
        self.mode = mode

    def getFiles(self):
        results = []

        for fDir, fSubDir, fNames in os.walk(self.src.dir):
            for fName in fNames:
                matched = False
                for exclusion in self.src.exclusions:
                    if re.match(exclusion, os.path.join(fDir, fName)):
                        matched = True
                        break
                if not matched:
                    results.append(os.path.join(fDir, fName))

        return results

    def send(self, destDecl, filePath):
        if self.src.id != "local":
            raise NotImplementedError("Source must be local")

        dirPart = re.match(self.src.dir + "(.*)", filePath).group(1)
        destFile = os.path.join(destDecl.dir, dirPart)

        if destDecl.id == "local":
            lUpload(filePath, destFile, skipIfExists = self.mode == "exists")
        else:
            upload(destinations[destDecl.id], filePath, destFile, skipIfExists = self.mode == "exists")

################################################################################
#                                                                              #
# Parsing                                                                      #
#                                                                              #
################################################################################

# Functions

def getDataFile():
    if len(sys.argv) != 2:
        print("Invalid number of arguments, a deploy file must be provided.")
        sys.exit(1)
    dataFile = sys.argv[1]
    if not os.path.exists(dataFile):
        print("Inavlid deploy file provided, the file could not be found.")
        sys.exit(1)
    return dataFile

def getDestinations(val):
    destinationMap = {'local' : LocalDestination()}
    for dest in val['destinations']:
        destinationMap[dest['id']] = RemoteDestination(dest['id'], dest['user'], dest['addr'])

    return destinationMap

def getTargetDefs(val):
    targetDefs = []
    targetDef = val['targets']

    # File definitions
    for fileDef in targetDef['files']:
        srcDict = fileDef['src']

        dests = []
        for dest in fileDef['dest']:
            dests.append(DestDecl(dest['id'], dest['dir']))

        targetDefs.append(FileTarget(fileDef['id'], fileDef['name'], FileSource(srcDict['id'], srcDict['expr'], srcDict['dir']), dests))

    # Mapping definitions
    for mappingDef in targetDef['mappings']:
        srcDict = mappingDef['src']

        dests = []
        for dest in mappingDef['dest']:
            dests.append(DestDecl(dest['id'], dest['dir']))

        targetDefs.append(MapTarget(mappingDef['id'], mappingDef['mode'], MapSource(srcDict['id'], srcDict['dir'], srcDict['exclusion']), dests))

    return targetDefs

# Operation

data = open(getDataFile())
val = json.load(data)

destinations = getDestinations(val)
targetDefs = getTargetDefs(val)

################################################################################
#                                                                              #
# Target Upload                                                                #
#                                                                              #
################################################################################

# Functions

def rightAlign(mainText, rightColumn):
    columns, lines = os.get_terminal_size()
    return (mainText + "{:>" + str(columns - len(mainText)) + "}").format(rightColumn)

def getHostKeyData(hostname):
    hostKeyType = None
    hostKey = None
    try:
        host_keys = paramiko.util.load_host_keys(os.path.expanduser('~/.ssh/known_hosts'))
    except IOError:
        try:
            # try ~/ssh/ too, because windows can't have a folder named ~/.ssh/
            host_keys = paramiko.util.load_host_keys(os.path.expanduser('~/ssh/known_hosts'))
        except IOError:
            host_keys = {}

    if hostname in host_keys:
        hostKeyType = host_keys[hostname].keys()[0]
        hostKey = host_keys[hostname][hostKeyType]

    return hostKey, hostKeyType

def promptForPass():
    return getpass("  Enter password: ")

def getPass(dest):
    if dest.password == None:
        dest.password = promptForPass()

    return dest.password

def lUpload(srcPath, destPath, skipIfExists):
    if skipIfExists and os.path.exists(destPath):
        return True

    destDir = os.path.dirname(destPath)
    if not os.path.exists(destDir):
        os.makedirs(destDir)
    shutil.copyfile(srcPath, destPath)
    return True

def renameUpload(sftp, src, dest):
    sftp.put(src, dest + ".temp")
    sftp.remove(dest);
    sftp.rename(dest + ".temp", dest)

def upload(dest, srcPath, destPath, skipIfExists = False):
    username = dest.user
    hostname = dest.hostname
    port = dest.port

    hostKey, hostKeyType = getHostKeyData(hostname)

    if hostKey == None or hostKeyType == None:
        print("  Failed to find a valid host key, cancelled!")
        sys.exit(2)

    attempts = 0
    while not (attempts >= 3 or attempts == -1):
        try:
            t = paramiko.Transport((hostname, port))

            t.connect(hostKey, username, getPass(dest))
            # t.connect(hostkey, username, None, gss_host=socket.getfqdn(hostname),
            #           gss_auth=True, gss_kex=True)

            attempts = -1

            sftp = SFTPClient.from_transport(t)

            # This is pretty awful, if the file doesn't exists it throws
            # an exception, and then we should continue

            # Assume true
            exists = True

            if skipIfExists:
                try:
                    sftp.stat(destPath)
                except IOError as e:
                    exists = False
                    if e[0] != 2:
                        pass

            if not skipIfExists or not exists:
                renameUpload(sftp, srcPath, destPath)

            t.close()

            return True
        except AuthenticationException as e:
            attempts += 1
            print("  Authentication error, please try again! (Failed attempts: " + str(attempts) + "/3)")
            dest.password = None
        except Exception as e:
            print('*** Caught exception: %s: %s' % (e.__class__, e))
            traceback.print_exc()
            sys.exit(1)
        finally:
            try:
                t.close()
            except:
                pass
    return False

# Operation
for target in targetDefs:
    print("Processing target " + target.id + "...")
    filePaths = target.getFiles()
    for filePath in filePaths:
        for destDecl in target.destDecls:
            idStr = destinations[destDecl.id].getIdentifierStr()
            print(rightAlign("  Tranfering " + filePath + "...", idStr), end='\r')
            target.send(destDecl, filePath)
            print(rightAlign("    " + filePath + " done!", idStr))

print("Process completed successfully!")
