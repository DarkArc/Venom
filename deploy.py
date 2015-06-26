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

class TargetDefinition:
    def __init__(self, id, src, dests):
        self.id = id
        self.src = src
        self.dests = dests

################################################################################
#                                                                              #
# Parsing                                                                      #
#                                                                              #
################################################################################

# Functions

def getDestinations(val):
    destinationMap = {'local' : LocalDestination()}
    for dest in val['destinations']:
        destinationMap[dest['id']] = RemoteDestination(dest['id'], dest['user'], dest['addr'])

    return destinationMap

def getTargetDefs(val):
    targetDefs = []
    for targetDef in val['targets']:
        srcDict = targetDef['src']

        dests = []
        for dest in targetDef['dest']:
            dests.append(Path(dest['id'], dest['name'], dest['dir']))

        targetDefs.append(TargetDefinition(targetDef['id'], Path(srcDict['id'], srcDict['name'], srcDict['dir']), dests))

    return targetDefs

# Operation

data = open('test_deploy.json')
val = json.load(data)

destinations = getDestinations(val)
targetDefs = getTargetDefs(val)

################################################################################
#                                                                              #
# Target Selection                                                             #
#                                                                              #
################################################################################

# Functions

def listTargets(targetDefs):
    print("Avalible targets:")
    for index, targetDef in enumerate(targetDefs):
        print(str(index + 1) + ") " + targetDef.id)
    print("\nNote: Select targets by their listed ID number seperated by a space, or * for all")
    return targetDefs

def promptForTargets():
    return input("Please select the targets which you wish to upload: ")

def selectTargets(targetDefs):
    selectedTargets = []
    for ID in promptForTargets().split():
        if ID == "*":
            selectedTargets = targetDefs
            break
        selectedTargets.append(targetDefs[int(ID) - 1])

    return selectedTargets

# Operation

selectedTargets = selectTargets(listTargets(targetDefs))

################################################################################
#                                                                              #
# Destination Selection                                                        #
#                                                                              #
################################################################################

# Functions

def listDestinations(dests):
    print("Avalible destinations:")
    values = sorted(dests, key = attrgetter('id'))
    for index, dest in enumerate(values):
        print(str(index + 1) + ") " + dest.id)
    print("\nNote: Select destinations by their listed ID number seperated by a space, or * for all")
    return values

def promptForDestinations():
    return input("Please select the destinations which you wish to upload to: ")

def selectDestinations(dests):
    global destinations
    for ID in promptForDestinations().split():
        if ID == "*":
            for dest in dests:
                destinations[dest.id].enabled = True
            break
        destinations[dests[int(ID) - 1].id].enabled = True

def askDestinationSelectionMode():
    print("Destination modes:");
    print("1) Global - One prompt (may prevent some targets from uploading)")
    print("2) Individual - Each target prompots")

    print("\nNote: Select mode by its listed ID number")
    return int(input("Please choose a mode: "))

globalSelection = askDestinationSelectionMode() == 1
if globalSelection:
    selectDestinations(listDestinations(list(destinations.values())))

################################################################################
#                                                                              #
# Target Upload                                                                #
#                                                                              #
################################################################################

# Functions

def createPath(dir, target):
    return dir + "/" + target

def rightAlign(mainText, rightColumn):
    columns, lines = os.get_terminal_size()
    return (mainText + "{:>" + str(columns - len(mainText)) + "}").format(rightColumn)

def mostRecentMatch(srcDir, srcTarget):
    matchCandidates = []

    for fEntry in os.listdir(srcDir):
        if re.match(srcTarget, fEntry):
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

for targetDef in selectedTargets:
    targetID = targetDef.id
    targetSrc = targetDef.src
    srcDecl = destinations[targetSrc.id]

    srcDir = targetSrc.dir
    srcTarget = mostRecentMatch(srcDir, targetSrc.name)
    srcPath = createPath(srcDir, srcTarget)

    print("\nUploading " + targetID + " (" + srcTarget + ")...")
    print(rightAlign("Target source: " + srcPath, srcDecl.getIdentifierStr()))

    if not globalSelection:
        selectDestinations(listDestinations(targetDef.dests))

    for targetDest in targetDef.dests:
        destDecl = destinations[targetDest.id]

        if destDecl == None:
            print("  Invalid remote specified, skipping!")

        if not destDecl.enabled:
            continue

        destDir = targetDest.dir
        destTarget = targetDest.name
        destPath = createPath(destDir, destTarget)

        print(rightAlign("  Destination: " + destPath, destDecl.getIdentifierStr()))


        if destDecl.id == "local":
            successful = lUpload(destDecl, srcPath, destPath)
        else:
            successful = upload(destDecl, srcPath, destPath)

        if (successful):
            print("  " + destTarget + " processed successfully!")
        else:
            print("  Processing of " + destTarget + " was unsuccessful!")
