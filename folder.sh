#!/usr/bin/env sh
# 根据文件名是否包含 vr / VR 判断目录

input="$1"
case "$input" in
  *[vV][rR]* )
    echo "VR"
    ;;
  * )
    echo "2D"
    ;;
esac
