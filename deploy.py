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

    def set_pass(self, password):
        self.password = password

    def get_pass(self):
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

# Parsing

data = open('test_deploy.json')
val = json.load(data)

destinationMap = dict()
for dest in val['destinations']:
    destinationMap[dest['id']] = Destination(dest['id'], dest['user'], dest['addr'])

fileDefs = []
for fileDef in val['files']:
    srcDict = fileDef['src']

    dests = []
    for dest in fileDef['dest']:
        dests.append(Path(dest['id'], dest['name'], dest['dir']))

    fileDefs.append(FileDefinition(fileDef['id'], Path(srcDict['id'], srcDict['name'], srcDict['dir']), dests))

# File selection

print("Avalible files:")
for index, fileDef in enumerate(fileDefs):
    print(str(index + 1) + ") " + fileDef.id)
print("\nNote: Select files by their listed ID number seperated by a space, or * for all")
selectIDs = input("Please select the files which you wish to upload: ")

selectedFiles = []
for ID in selectIDs.split():
    if ID == "*":
        selectedFiles = fileDefs
        break
    selectedFiles.append(fileDefs[int(ID) - 1])

# File upload

for fileDef in selectedFiles:
    fileID = fileDef.id
    srcID = fileDef.src.id
    srcDir = fileDef.src.dir
    srcFile = fileDef.src.name

    matchCandidates = []

    for fEntry in os.listdir(srcDir):
        if re.match(srcFile, fEntry):
            matchCandidates.append((fEntry, os.path.getmtime(srcDir + "/" + fEntry)))

    srcFile = sorted(matchCandidates, key = itemgetter(1), reverse = True)[0][0]

    print("\nUploading " + fileID + " (" + srcFile + ") from: " + srcDir + "   [" + srcID + "]")

    for dest in fileDef.dests:
        destMapObj = destinationMap[dest.id]

        destID = dest.id
        destDir = dest.dir
        destFile = dest.name

        username = destMapObj.user
        hostname = destMapObj.addr

        port = 22

        if hostname.find(':') >= 0:
            hostname, portstr = hostname.split(':')
            port = int(portstr)

        print("Destination: " + destDir + "/" + destFile + "   [" + destID + " - " + hostname + ":" + str(port) + "]")

        hostkeytype = None
        hostkey = None
        try:
            host_keys = paramiko.util.load_host_keys(os.path.expanduser('~/.ssh/known_hosts'))
        except IOError:
            try:
                # try ~/ssh/ too, because windows can't have a folder named ~/.ssh/
                host_keys = paramiko.util.load_host_keys(os.path.expanduser('~/ssh/known_hosts'))
            except IOError:
                print('*** Unable to open host keys file')
                host_keys = {}

        if hostname in host_keys:
            hostkeytype = host_keys[hostname].keys()[0]
            hostkey = host_keys[hostname][hostkeytype]
            print('Using host key of type %s' % hostkeytype)

        if hostkeytype == None:
            print('Failed to find a valid host key, cancelled!')
            sys.exit(2)

        try:
            t = paramiko.Transport((hostname, port))

            # If there's no password stored, take one
            if destMapObj.get_pass() == None:
                password = getpass("Enter password: ")
                destMapObj.set_pass(password)

            t.connect(hostkey, username, password)
            # t.connect(hostkey, username, None, gss_host=socket.getfqdn(hostname),
            #           gss_auth=True, gss_kex=True)
            sftp = paramiko.SFTPClient.from_transport(t)

            # move file
            sftp.put(srcDir + '/' + srcFile, destDir + '/' + destFile + ".temp")
            sftp.remove(destDir + '/' + destFile);
            sftp.rename(destDir + '/' + destFile + ".temp", destDir + '/' + destFile)

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
