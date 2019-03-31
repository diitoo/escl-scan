#!/usr/bin/env python3
#
# License:
#   MIT
# Author:
#   diitoo
# Inspired by:
# - https://bugs.launchpad.net/hplip/+bug/1811504
# - https://github.com/kno10/python-scan-eSCL
# - https://github.com/ziman/scan-eSCL/
# - http://testcluster.blogspot.com/2014/03/scanning-from-escl-device-using-command.html

import argparse
import datetime
import logging
import os.path
import requests
import sys
import time
from io import StringIO
from lxml import etree
from urllib.parse import urljoin

DEF_NAME = "scan"
SIZES = {"a4": (2480, 3508), "a5": (1748, 2480), "b5": (2079, 2953), "us": (2550, 3300)}  # approx. real widths and heights (in mm) times 11.81
MAX_POLL = 50
NS_SCAN = "http://schemas.hp.com/imaging/escl/2011/05/03"
NS_PWG = "http://www.pwg.org/schemas/2010/12/sm"
SCAN_REQUEST = """
<?xml version="1.0" encoding="UTF-8"?>
<scan:ScanSettings xmlns:pwg="__NS_PWG__" xmlns:scan="__NS_SCAN__">
  <pwg:Version>__VERSION__</pwg:Version>
  <pwg:ScanRegions>
    <pwg:ScanRegion>
      <pwg:XOffset>0</pwg:XOffset>
      <pwg:YOffset>0</pwg:YOffset>
      <pwg:Width>__WIDTH__</pwg:Width>
      <pwg:Height>__HEIGHT__</pwg:Height>
      <pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>
    </pwg:ScanRegion>
  </pwg:ScanRegions>
  <pwg:InputSource>Platen</pwg:InputSource>
  <pwg:DocumentFormat>__FORMAT__</pwg:DocumentFormat>
  <scan:ColorMode>__COLORMODE__</scan:ColorMode>
  <scan:XResolution>__RESOLUTION__</scan:XResolution>
  <scan:YResolution>__RESOLUTION__</scan:YResolution>
</scan:ScanSettings>
""".strip()


def main(args):
    # logger
    logging.basicConfig(level=(logging.INFO, logging.DEBUG)[args.verbose or args.very_verbose])
    logging.getLogger("requests").setLevel(logging.WARN)
    log = logging.getLogger("scan")

    # url
    if not args.url.startswith("http://") and not args.url.startswith("https://"):
        error("Invalid URL: %s" % args.url)
    log.debug("URL: %s", args.url)

    # filename
    if args.out != "":
        filename = args.out
    else:
        filename = DEF_NAME + "_" + str(datetime.datetime.now().strftime("%Y%m%d-%H%M%S")) + "." + args.type
    if not args.info:
        log.debug("Filename: %s", filename)
        if os.path.isfile(filename):
            error("File exists already: %s" % filename)

    http = requests.Session()

    # query capabilities
    capUrl = urljoin(args.url, "eSCL/ScannerCapabilities")
    log.debug("Querying scanner capabilities: %s", capUrl)
    resp = http.get(capUrl)
    resp.raise_for_status()
    tree = etree.fromstring(resp.content)
    if args.very_verbose:
        log.debug("Scanner capabilities: %s", str(etree.tostring(tree)).replace("\\n", "\n").replace("\\t", "  "))

    version = first(tree.xpath("//pwg:Version/text()", namespaces={"pwg": NS_PWG}))
    makeAndModel = first(tree.xpath("//pwg:MakeAndModel/text()", namespaces={"pwg": NS_PWG}))
    serialNumber = first(tree.xpath("//pwg:SerialNumber/text()", namespaces={"pwg": NS_PWG}))
    adminUri = first(tree.xpath("//scan:AdminURI/text()", namespaces={"scan": NS_SCAN}))
    formats = tree.xpath("//pwg:DocumentFormat/text()", namespaces={"pwg": NS_PWG})
    colorModes = tree.xpath("//scan:ColorMode/text()", namespaces={"scan": NS_SCAN})
    xResolutions = tree.xpath("//scan:XResolution/text()", namespaces={"scan": NS_SCAN})
    yResolutions = tree.xpath("//scan:YResolution/text()", namespaces={"scan": NS_SCAN})
    maxWidth = firstInt(tree.xpath("//scan:MaxWidth/text()", namespaces={"scan": NS_SCAN}))
    maxHeight = firstInt(tree.xpath("//scan:MaxHeight/text()", namespaces={"scan": NS_SCAN}))

    # query status
    statusUrl = urljoin(args.url, "eSCL/ScannerStatus")
    log.debug("Querying scanner status: %s", statusUrl)
    resp = http.get(statusUrl)
    resp.raise_for_status()
    tree = etree.fromstring(resp.content)
    if args.very_verbose:
        log.debug("Scanner status: %s", str(etree.tostring(tree)).replace("\\n", "\n").replace("\\t", "  "))
    status = first(tree.xpath("//pwg:State/text()", namespaces={"pwg": NS_PWG}))
    log.debug("Scanner status: %s", status)

    # information
    if args.info:
        print("Scanner model: %s" % makeAndModel)
        print("Serial number: %s" % serialNumber)
        print("Scanner URL:   %s" % args.url)
        print("Admin URL:     %s" % adminUri)
        print("Formats:       %s" % ", ".join(formats))
        print("Color Modes:   %s" % ", ".join(colorModes))
        print("X-Resolutions: %s" % ", ".join(xResolutions))
        print("Y-Resolutions: %s" % ", ".join(yResolutions))
        print("Max width:     %s" % maxWidth)
        print("Max height:    %s" % maxHeight)
        print("Status:        %s" % status)
        sys.exit(0)

    # format
    if args.type == "jpg":
        format = "image/jpeg"
    elif args.type == "pdf":
        format = "application/pdf"
    else:
        error("Invalid type: %s" % args.type)  # should never happen due to argparse
    log.debug("Format: '%s', supported: %s", format, formats)
    if format not in formats:
        error("Unsupported format: '%s', supported: %s" % (format, formats))

    # color mode
    if args.color_mode == "r24":
        colorMode = "RGB24"
    elif args.color_mode == "g8":
        colorMode = "Grayscale8"
    else:
        error("Invalid color mode: %s" % args.color_mode)  # should never happen due to argparse
    log.debug("Color mode: '%s', supported: %s", colorMode, colorModes)
    if colorMode not in colorModes:
        error("Unsupported color mode: '%s', supported: %s" % (colorMode, colorModes))

    # resolution
    if args.resolution == '':
        resolution = max([value for value in xResolutions if value in yResolutions])
    else:
        resolution = args.resolution
    log.debug("Resolution: %s, supported X: %s, supported Y: %s", resolution, xResolutions, yResolutions)
    if resolution not in xResolutions:
        error("Unsupported x-resolution '%s', supported: %s" % (resolution, xResolutions))
    if resolution not in yResolutions:
        error("Unsupported y-resolution '%s', supported: %s" % (resolution, yResolutions))

    # width/height
    if args.size == "max":
        width = maxWidth
        height = maxHeight
    else:
        (width, height) = SIZES[args.size]
    if width > maxWidth:
        error("Invalid width: %d, maximum: %d" % (width, maxWidth))
    if height > maxHeight:
        error("Invalid height: %d, maximum: %d" % (height, maxHeight))
    log.debug("Width: %d, maxWidth: %d", width, maxWidth)
    log.debug("Height: %d, maxHeight: %d", height, maxHeight)

    # start scanning
    log.debug("Version: %s", version)
    if status != "Idle":
        error("Invalid scanner status: %s" % status)
    startUrl = urljoin(args.url, "eSCL/ScanJobs")
    startReq = SCAN_REQUEST.replace(
        "__NS_SCAN__", NS_SCAN).replace(
        "__NS_PWG__", NS_PWG).replace(
        "__VERSION__", version).replace(
        "__FORMAT__", format).replace(
        "__COLORMODE__", colorMode).replace(
        "__RESOLUTION__", resolution).replace(
        "__WIDTH__", str(width)).replace(
        "__HEIGHT__", str(height))
    if args.very_verbose:
        log.debug("Sending scan request to %s: %s", startUrl, startReq)
    else:
        log.debug("Sending scan request: %s", startUrl)
    resp = http.post(startUrl, startReq, headers={"Content-Type": "text/xml"})
    resp.raise_for_status()
    resultUrl = urljoin(resp.headers["Location"] + "/", "NextDocument")  # status code is 201 so Requests won't follow Location
    log.debug("Result is at %s", resultUrl)

    # poll for the result every two seconds, give up after 10 failures
    counter = 1
    while True:
        time.sleep(2)
        log.debug("Polling [%d]: %s", counter, resultUrl)
        resp = http.get(resultUrl)
        if resp.status_code == 200:
            log.debug("Received result")
            break
        counter += 1
        if counter > MAX_POLL:
            error("Giving up after %d attempts to load result, try it manually later: curl -s %s > %s" % (MAX_POLL, resultUrl, filename))

    # write result
    log.debug("Writing: %s", filename)
    with open(filename, "wb") as f:
        f.write(resp.content)
    print(filename)


def first(a, default=None):
    return a[0] if a else default


def firstInt(a, default=None):
    f = first(a)
    return int(f) if f else default


def error(msg):
    print(msg)
    sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="A little Python3 script for scanning via the eSCL protocol")
    ap.add_argument("-i", "--info", action="store_true", help="show scanner information and exit")
    ap.add_argument("-o", "--out", default="", help="output file name [default: " + DEF_NAME + "_<datetime>.<type>]")
    ap.add_argument("-t", "--type", default="jpg", help="desired resulting file type [default: %(default)s]", choices=["jpg", "pdf"])
    ap.add_argument("-r", "--resolution", default="", help="a single value for both X and Y resolution [default: max. available]")
    ap.add_argument("-c", "--color-mode", default="r24", help="RGB24 (r24) or Grayscale8 (g8) [default: %(default)s]", choices=["r24", "g8"])
    ap.add_argument("-s", "--size", default="max", help="size of scanned paper [default: %(default)s]", choices=["a4", "a5", "b5", "us", "max"])
    ap.add_argument("-v", "--verbose", action="store_true", help="Show debug output")
    ap.add_argument("-V", "--very-verbose", action="store_true", help="Show debug output and all data")
    ap.add_argument("url", help="URL of the scanner, incl. scheme and (if necessary) port")
    main(ap.parse_args())
