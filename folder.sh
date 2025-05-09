#!/usr/bin/env sh
# folder.sh — 根据文件名是否含 vr (不区分大小写) 决定目录

input="$1"
case "$input" in
  *[vV][rR]* )
    echo "VR"
    ;;
  * )
    echo "2D"
    ;;
esac
