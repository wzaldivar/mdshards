#!/bin/bash -eu
# The fuzz targets and their build live upstream; see backend/fuzz/.
exec "$SRC/mdshards/.clusterfuzzlite/build.sh"
