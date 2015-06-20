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

class Destination:
    def __init__(self, id):
        self.id = id
        self.enabled = False

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

class Path:
    def __init__(self, id, name, dir):
        self.id = id
        self.name = name
        self.dir = dir

class FileDefinition:
    def __init__(self, id, src, dests):
        self.id = id
        self.src = src
        self.dests = dests

################################################################################
#                                                                              #
# Parsing                                                                      #
#                                                                              #
################################################################################

#Functions

def getDestinations(val):
    destinationMap = {'local' : LocalDestination()}
    for dest in val['destinations']:
        destinationMap[dest['id']] = RemoteDestination(dest['id'], dest['user'], dest['addr'])

    return destinationMap

def getFileDefs(val):
    fileDefs = []
    for fileDef in val['files']:
        srcDict = fileDef['src']

        dests = []
        for dest in fileDef['dest']:
            dests.append(Path(dest['id'], dest['name'], dest['dir']))

        fileDefs.append(FileDefinition(fileDef['id'], Path(srcDict['id'], srcDict['name'], srcDict['dir']), dests))

    return fileDefs

# Operation

data = open('test_deploy.json')
val = json.load(data)

destinations = getDestinations(val)
fileDefs = getFileDefs(val)

################################################################################
#                                                                              #
# File Selection                                                               #
#                                                                              #
################################################################################

# Functions

def listFiles(fileDefs):
    print("Avalible files:")
    for index, fileDef in enumerate(fileDefs):
        print(str(index + 1) + ") " + fileDef.id)
    print("\nNote: Select files by their listed ID number seperated by a space, or * for all")
    return fileDefs

def promptForFiles():
    return input("Please select the files which you wish to upload: ")

def selectFiles(fileDefs):
    selectedFiles = []
    for ID in promptForFiles().split():
        if ID == "*":
            selectedFiles = fileDefs
            break
        selectedFiles.append(fileDefs[int(ID) - 1])

    return selectedFiles

# Operation

selectedFiles = selectFiles(listFiles(fileDefs))

################################################################################
#                                                                              #
# Destination Selection                                                        #
#                                                                              #
################################################################################

# Functions

def listDestinations(destinations):
    print("Avalible destinations:")
    values = sorted(list(destinations.values()), key = attrgetter('id'))
    for index, dest in enumerate(values):
        print(str(index + 1) + ") " + dest.id)
    print("\nNote: Select destinations by their listed ID number seperated by a space, or * for all")
    return values

def promptForDestinations():
    return input("Please select the destinations which you wish to upload to: ")

def selectDestinations(destinations):
    for ID in promptForDestinations().split():
        if ID == "*":
            for dest in destinations:
                dest.enabled = True
            break
        destinations[int(ID) - 1].enabled = True

    return selectedFiles

# Operation

selectDestinations(listDestinations(destinations))

################################################################################
#                                                                              #
# File Upload                                                                  #
#                                                                              #
################################################################################

# Functions

def createPath(dir, file):
    return dir + "/" + file

def rightAlign(mainText, rightColumn):
    columns, lines = os.get_terminal_size()
    return (mainText + "{:>" + str(columns - len(mainText)) + "}").format(rightColumn)

def mostRecentMatch(srcDir, srcFile):
    matchCandidates = []

    for fEntry in os.listdir(srcDir):
        if re.match(srcFile, fEntry):
            matchCandidates.append((fEntry, os.path.getmtime(srcDir + "/" + fEntry)))

    return sorted(matchCandidates, key = itemgetter(1), reverse = True)[0][0]



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

def lUpload(destDecl, srcPath, destPath):
    shutil.copyfile(srcPath, destPath)
    return True

def renameUpload(sftp, src, dest):
    sftp.put(src, dest + ".temp")
    sftp.remove(dest);
    sftp.rename(dest + ".temp", dest)

def upload(destDecl, srcPath, destPath):
    username = destDecl.user
    hostname = destDecl.hostname
    port = destDecl.port

    hostKey, hostKeyType = getHostKeyData(hostname)

    if hostKey != None and hostKeyType != None:
        print("  Using host key of type " + hostKeyType)
    else:
        print("  Failed to find a valid host key, cancelled!")
        sys.exit(2)

    attempts = 0
    while not (attempts >= 3 or attempts == -1):
        try:
            t = paramiko.Transport((hostname, port))

            t.connect(hostKey, username, getPass(destDecl))
            # t.connect(hostkey, username, None, gss_host=socket.getfqdn(hostname),
            #           gss_auth=True, gss_kex=True)

            attempts = -1

            renameUpload(SFTPClient.from_transport(t), srcPath, destPath)

            t.close()

            return True
        except AuthenticationException as e:
            attempts += 1
            print("  Authentication error, please try again! (Failed attempts: " + str(attempts) + "/3)")
            destDecl.password = None
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

for fileDef in selectedFiles:
    fileID = fileDef.id
    fileSrc = fileDef.src
    srcDecl = destinations[fileSrc.id]

    srcDir = fileSrc.dir
    srcFile = mostRecentMatch(srcDir, fileSrc.name)
    srcPath = createPath(srcDir, srcFile)

    print("\nUploading " + fileID + " (" + srcFile + ")...")
    print(rightAlign("File source: " + srcPath, srcDecl.getIdentifierStr()))

    for fileDest in fileDef.dests:
        destDecl = destinations[fileDest.id]

        if destDecl == None:
            print("  Invalid remote specified, skipping!")

        destID = destDecl.id
        destDir = fileDest.dir
        destFile = fileDest.name
        destPath = createPath(destDir, destFile)

        print(rightAlign("  Destination: " + destPath, destDecl.getIdentifierStr()))

        if not destDecl.enabled:
            print("  " + destFile + " skipped, the destination '" + destID + "' was not enabled!")
            continue

        if destDecl.id == "local":
            successful = lUpload(destDecl, srcPath, destPath)
        else:
            successful = upload(destDecl, srcPath, destPath)

        if (successful):
            print("  " + destFile + " processed successfully!")
        else:
            print("  Processing of " + destFile + " was unsuccessful!")
