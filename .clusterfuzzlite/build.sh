#!/bin/bash -eu
# Builds the Atheris fuzz targets in backend/fuzz/. Shared by ClusterFuzzLite
# (this directory) and the OSS-Fuzz project, whose build.sh just execs this.
cd "$SRC/mdshards/backend"
pip3 install --no-cache-dir -r requirements.txt

for fuzzer in fuzz/fuzz_*.py; do
  compile_python_fuzzer "$fuzzer" --paths "$PWD"
done
cp fuzz/*.dict "$OUT/"
