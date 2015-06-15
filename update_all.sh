#!/bin/bash

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

echo "Starting upload process..."

# Determin project

echo "Projects availible:"
echo "- Skree"
echo "- Sponge"

echo "Please enter the project you would like to update (* for all):"
read PROJ

DONE=0

# Process Skree
if [[ "$PROJ" == "Skree" || "$PROJ" == "*" ]]
  then
    echo "Processing Skree..."
    sftp -b skree_batch.txt Dark_Arc@server.skelril.com
    DONE=1
  fi

# Process Sponge
if [[ "$PROJ" == "Sponge" || "$PROJ" == "*" ]]
  then
    echo "Processing Sponge..."
    sftp -b sponge_batch.txt Dark_Arc@server.skelril.com
    DONE=1
  fi

# No project!
if [[ "$DONE" == 1 ]]
  then
    echo "Request completed successfully!"
  else
    echo "Invalid project, terminating!"
  fi
