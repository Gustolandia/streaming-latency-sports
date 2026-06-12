#!/usr/bin/env bash
# Wrapper to call Windows docker from bash in WSL2
# Usage: docker-cmd.sh [docker args...]

# Collect all arguments
args=("$@")

# Call Windows docker.exe through cmd.exe
# We need to use the Windows path to docker.exe
cmd.exe /c "docker ${args[*]} " 2>&1
