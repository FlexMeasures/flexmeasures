#!/usr/bin/env python

"""
Script for initialising the documentation
"""
import os
from slugify import slugify
from subprocess import call
from selenium import webdriver
from PIL import Image, ImageOps

path_to_doc = "documentation"
path_return = ".."
if os.getcwd().endswith("scripts"):
    path_to_doc = "../documentation"
    path_return = "../scripts"

make_docs_cmd = "cd %s; make html; cd %s" % (path_to_doc, path_return)
if os.name != "posix":
    make_docs_cmd = make_docs_cmd.replace(";", " &")

    # here we re-activate the virtual environment first
    make_docs_cmd = "activate a1-venv & " + make_docs_cmd


def initialise_screen_shots(views):
    width = 1500
    max_height = 3000
    browser = webdriver.Firefox()
    browser.set_window_position(0, 0)
    browser.set_window_size(width, max_height)
    for view in views:
        print("Saving " + view)
        url = "http://127.0.0.1:5000/" + view
        browser.get(url)
        output_file = "../documentation/img/screenshot_" + slugify(view) + ".png"
        browser.save_screenshot(output_file)
    browser.close()

    # remove trailing white rows from the image
    for view in views:
        output_file = "../documentation/img/screenshot_" + slugify(view) + ".png"
        im = Image.open(output_file)
        im.crop(ImageOps.invert(im.convert("RGB")).getbbox()).save(output_file)

    return


def initialise_docs():
    """Initialise doc files"""

    print("Processing documentation files ...")

    call(make_docs_cmd, shell=True)


if __name__ == "__main__":
    """Initialise screen shots and documentation"""

    initialise_screen_shots(
        [
            "dashboard",
            "portfolio",
            "control",
            "analytics",
            "dashboard?prosumer_mock=vehicles",
            "portfolio?prosumer_mock=vehicles",
            "control?prosumer_mock=vehicles",
        ]
    )
    initialise_docs()
