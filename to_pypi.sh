#!/bin/bash


# Script to release FlexMeasures to Pypi
#
# Either as dev package:    ./to_pypi.sh dev [some_number]  # will compile a number from the git revision of not given
# Or as official release:   ./to_pypi release


read -p "Are you sure you don't have a config file within these folders (which might get sent along)? [yN] " -n 1 -r
echo    # move to a new line
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "Exiting ..."
    exit 1
fi
echo "Alright, then ..."

rm -rf build/* dist/*

pip -q install twine

python setup.py -q alias -u release egg_info -Db ""


if [ "$1" = "dev" ]; then
    if [ "$2" != "" ]; then
        dev_number=$2
        cleandevtag=${dev_number//[^0-9]/}  # only numbers
        if [ "$cleandevtag" != "$dev_number" ]; then
            echo "Only numbers in the dev tag please! (leave out x.y.z.dev)"
            exit 2
        fi
        echo "Using $dev_number as dev build number ..."
    else
        revisioncount=`git log --oneline | wc -l`
        projectversion=`git describe --tags --always --long`
        cleanversion=${projectversion//[a-z]/}  # only numbers
        dev_number=$cleanversion$revisioncount
        echo "Using $dev_number as dev build number ..."
    fi

    python setup.py -q alias -u dev egg_info --tag-build=.dev$dev_number
    python setup.py dev sdist
    python setup.py dev bdist_wheel
elif [ "$1" = "release" ]; then
    python setup.py release sdist
    python setup.py release bdist_wheel
else
    echo "Argument needs to be release or dev"
    exit 2
fi

twine upload --verbose dist/*
