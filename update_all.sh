#!/bin/bash
echo Starting upload process...

# Determin project

echo Projects availible:
echo - Skree
echo - Sponge

echo "Please enter the project you would like to update (* for all):"
read PROJ

DONE=$false

# Process Skree
if [[ "$PROJ" == "Skree" || "$PROJ" == "*" ]]
  then
    echo Processing Skree...
    sftp -b skree_batch.txt Dark_Arc@server.skelril.com
  fi

# Process Sponge
if [[ "$PROJ" == "Sponge" || "$PROJ" == "*" ]]
  then
    echo Processing Sponge...
    sftp -b sponge_batch.txt Dark_Arc@server.skelril.com
    exit 0
  fi

# No project!
if [[ "$DONE" == true]]
  then
    echo Request completed successfully!
  else
    echo Invalid project, terminating!
  fi
