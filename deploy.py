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
import paramiko
from operator import itemgetter
from getpass import getpass

class Destination:
    def __init__(self, id, user, addr):
        self.id = id
        self.user = user
        self.addr = addr
        self.password = None

    def setPass(self, password):
        self.password = password

    def getPass(self):
        return self.password

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
    destinationMap = dict()
    for dest in val['destinations']:
        destinationMap[dest['id']] = Destination(dest['id'], dest['user'], dest['addr'])

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

listFiles(fileDefs)
selectedFiles = selectFiles(fileDefs)

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

def deriveRemoteDetails(hostname):
    port = 22

    if hostname.find(':') >= 0:
        hostname, portstr = hostname.split(':')
        port = int(portstr)

    return hostname, port

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
    return getpass("Enter password: ")

def getPass(dest):
    if dest.getPass() == None:
        dest.setPass(promptForPass())

    return dest.getPass()

def renameUpload(sftp, src, dest):
    sftp.put(src, dest + ".temp")
    sftp.remove(dest);
    sftp.rename(dest + ".temp", dest)

# Operation

for fileDef in selectedFiles:
    fileID = fileDef.id
    srcID = fileDef.src.id
    srcDir = fileDef.src.dir
    srcFile = mostRecentMatch(srcDir, fileDef.src.name)

    print("\nUploading " + fileID + " (" + srcFile + ")...")
    print(rightAlign("File source: " + createPath(srcDir, srcFile), "[" + srcID + "]"))

    for fileDest in fileDef.dests:
        destDecl = destinations[fileDest.id]

        destID = fileDest.id
        destDir = fileDest.dir
        destFile = fileDest.name

        username = destDecl.user
        hostname, port = deriveRemoteDetails(destDecl.addr)

        print(rightAlign("Destination: " + createPath(destDir, destFile), "[" + destID + " - " + hostname + ":" + str(port) + "]"))

        hostKey, hostKeyType = getHostKeyData(hostname)

        if hostKey != None and hostKeyType != None:
            print("Using host key of type " + hostKeyType)
        else:
            print("Failed to find a valid host key, cancelled!")
            sys.exit(2)

        try:
            t = paramiko.Transport((hostname, port))

            t.connect(hostKey, username, getPass(destDecl))
            # t.connect(hostkey, username, None, gss_host=socket.getfqdn(hostname),
            #           gss_auth=True, gss_kex=True)
            sftp = paramiko.SFTPClient.from_transport(t)

            renameUpload(sftp, createPath(srcDir, srcFile), createPath(destDir, destFile))

            print(destFile + " uploaded successfully!")

            t.close()

        except Exception as e:
            print('*** Caught exception: %s: %s' % (e.__class__, e))
            traceback.print_exc()
            try:
                t.close()
            except:
                pass
            sys.exit(1)
