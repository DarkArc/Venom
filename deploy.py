# Venom - Deployment script
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
import signal
import shutil
import paramiko
import traceback
from getpass import getpass
from operator import itemgetter, attrgetter
from paramiko import SFTPClient
from paramiko.ber import BERException
from paramiko.ssh_exception import AuthenticationException, SSHException

def signal_handler(signal, frame):
    print('\nExecution halted!')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

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
        self.connection = None
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

    def getTarget(self, destDecl, filePath):
        if self.src.id != "local":
            raise NotImplementedError("Source must be local")

        return os.path.join(destDecl.dir, self.name)

    def send(self, destDecl, filePath, callBack):
        destFile = self.getTarget(destDecl, filePath)

        if destDecl.id == "local":
            callBack()
            lUpload(filePath, destFile)
        else:
            upload(destinations[destDecl.id], filePath, destFile, callBack)

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

    def getTarget(self, destDecl, filePath):
        if self.src.id != "local":
            raise NotImplementedError("Source must be local")

        dirPart = re.match(self.src.dir + "(.*)", filePath).group(1)
        return os.path.join(destDecl.dir, dirPart)

    def send(self, destDecl, filePath, callBack):
        destFile = self.getTarget(destDecl, filePath)

        if destDecl.id == "local":
            callBack()
            lUpload(filePath, destFile, skipIfExists = self.mode == "exists")
        else:
            upload(destinations[destDecl.id], filePath, destFile, callBack, skipIfExists = self.mode == "exists")

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

def rightAlign(mainText, rightColumn, indent = 0, leftPriority = False):
    try:
        columns, lines = os.get_terminal_size()
        spaces = indent * 2
        if (len(mainText) + len(rightColumn) + 2 + spaces) > columns:
            if leftPriority:
                mainText = mainText[:columns - len(rightColumn) - 5 - spaces] + '...  '
            else:
                mainText = '...' + mainText[-(columns - len(rightColumn) - 5 - spaces):] + '  '

        mainText = (' ' * spaces) + mainText

        return (mainText + "{:>" + str(columns - len(mainText)) + "}").format(rightColumn)
    except OSError as err:
        return (mainText + rightColumn)

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

def authenticate(dest):
    print(rightAlign("Authenticating...", dest.getIdentifierStr()))

    if dest.id == "local":
        return

    attempts = 0
    while not (attempts >= 3 or attempts == -1):
        try:
            username = dest.user
            hostname = dest.hostname
            port = dest.port

            hostKey, hostKeyType = getHostKeyData(hostname)

            if hostKey == None or hostKeyType == None:
                print("  Failed to find a valid host key, cancelled!")
                sys.exit(2)

            dest.connection = paramiko.Transport((hostname, port))

            keyPath = os.path.expanduser('~') + '/.ssh/id_rsa'
            if (os.path.isfile(keyPath)):
                print(rightAlign("Attempting to login via private key auth", dest.getIdentifierStr()))

                privateKey = paramiko.RSAKey.from_private_key_file(keyPath, getPass(dest))
                dest.connection.connect(hostKey, username, pkey = privateKey)
            else:
                print(rightAlign("Attempting to login via password auth", dest.getIdentifierStr()))

                dest.connection.connect(hostKey, username, getPass(dest))

            break

        except (AuthenticationException, SSHException, BERException) as e:
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

def closeConnection(dest):
    if dest.id == "local":
        return

    dest.connection.close()

def lUpload(srcPath, destPath, skipIfExists = False):
    if skipIfExists and os.path.exists(destPath):
        return True

    destDir = os.path.dirname(destPath)
    if not os.path.exists(destDir):
        os.makedirs(destDir)
    shutil.copyfile(srcPath, destPath)
    return True

def renameUpload(sftp, src, dest, callBack):
    targDir = os.path.dirname(dest)
    dirStack = [targDir]

    while True:
        curDir = dirStack.pop()
        try:
            sftp.stat(curDir)
            break
        except FileNotFoundError as e:
            dirStack.append(curDir)
            dirStack.append(os.path.split(curDir)[0])

    while len(dirStack) != 0:
        dir = dirStack.pop()
        sftp.mkdir(dir)

    sftp.put(src, dest + ".temp", callBack)
    try:
        sftp.stat(dest)
        sftp.remove(dest)
    except FileNotFoundError as e:
        pass

    sftp.rename(dest + ".temp", dest)

def upload(dest, srcPath, destPath, callBack, skipIfExists = False):
    try:
        sftp = SFTPClient.from_transport(dest.connection)

        # This is pretty awful, if the file doesn't exists it throws
        # an exception, and then we should continue

        # Assume true
        exists = True

        if skipIfExists:
            try:
                sftp.stat(destPath)
            except FileNotFoundError as e:
                exists = False

        if not skipIfExists or not exists:
            renameUpload(sftp, srcPath, destPath, callBack)
        else:
            callBack()

        return True
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

# Establish connections
for dest in destinations.values():
    authenticate(dest)

# Operation
for target in targetDefs:
    print("Processing target " + target.id + "...")
    filePaths = target.getFiles()
    for filePath in filePaths:
        print(rightAlign("Source path: " + filePath, "[local]", 2))
        for destDecl in target.destDecls:
            idStr = destinations[destDecl.id].getIdentifierStr()
            curFile = target.getTarget(destDecl, filePath);

            def progressCallback(transfered = -1, fileSize = -1):
                rightBlock = idStr
                if transfered != -1 and fileSize != -1:
                    rightBlock = "[" + str(int((transfered / fileSize) * 100)) + "%]" + rightBlock

                print(rightAlign("Tranfering " + curFile + "...", rightBlock, 1, True), end='\r')

            target.send(destDecl, filePath, progressCallback)
            print(rightAlign(curFile + " done!", idStr, 2))

# Close connections
for dest in destinations.values():
    closeConnection(dest)

print("Process completed successfully!")
