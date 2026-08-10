#!/usr/bin/env bash
set -e
ZIP="sycro-financial-github-upload.zip"
if [ ! -f "$ZIP" ]; then
  echo "Upload $ZIP to the repository root first."
  exit 1
fi
unzip -o "$ZIP" -d .
rm -rf __pycache__ .pytest_cache
find . -name '*.pyc' -delete
git add -A
git status --short
echo "Files are staged. Commit with: git commit -m 'Replace Sycro Financial deployment build'"
echo "Then push with: git push origin main"
