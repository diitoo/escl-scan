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
import requests
import sys
import time
from io import StringIO
from lxml import etree
from urllib.parse import urljoin

DEF_NAME = "scan"
MAX_POLL = 20
NS_SCAN = "http://schemas.hp.com/imaging/escl/2011/05/03"
NS_PWG = "http://www.pwg.org/schemas/2010/12/sm"
SCAN_REQUEST = """
<?xml version="1.0" encoding="UTF-8"?>
<scan:ScanSettings xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm" xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03">
  <pwg:Version>2.63</pwg:Version>
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
    log.debug("Filename: %s", filename)

    # format
    if args.type == "jpg":
        format = "image/jpeg"
    elif args.type == "pdf":
        format = "application/pdf"
    else:
        error("Invalid type: %s" % args.type)
    log.debug("Format: %s", format)

    # color mode
    if args.color_mode == "r24":
        colorMode = "RGB24"
    elif args.color_mode == "g8":
        colorMode = "Grayscale8"
    else:
        error("Invalid color mode: %s" % args.color_mode)
    log.debug("Color mode: %s", colorMode)

    http = requests.Session()

    # query capabilities
    capUrl = urljoin(args.url, "eSCL/ScannerCapabilities")
    log.debug("Querying scanner capabilities: %s", capUrl)
    resp = http.get(capUrl)
    resp.raise_for_status()
    tree = etree.fromstring(resp.content)
    log.debug("Scanner: %s", first(tree.xpath("//pwg:MakeAndModel/text()", namespaces={"pwg": NS_PWG})))
    log.debug("Serial number: %s", first(tree.xpath("//pwg:SerialNumber/text()", namespaces={"pwg": NS_PWG})))
    if args.very_verbose:
        log.debug("Scanner capabilities: %s", str(etree.tostring(tree)).replace("\\n", "\n").replace("\\t", "  "))

    # sanity check: format
    formats = tree.xpath("//pwg:DocumentFormat/text()", namespaces={"pwg": NS_PWG})
    log.debug("Supported formats: %s", formats)
    if format not in formats:
        error("Unsupported format: '%s', supported: %s" % (format, formats))

    # sanity check: color mode
    colorModes = tree.xpath("//scan:ColorMode/text()", namespaces={"scan": NS_SCAN})
    log.debug("Supported color modes: %s", colorModes)
    if colorMode not in colorModes:
        error("Unsupported color mode: '%s', supported: %s" % (colorMode, colorModes))

    # sanity check: resolution
    xResolutions = tree.xpath("//scan:XResolution/text()", namespaces={"scan": NS_SCAN})
    yResolutions = tree.xpath("//scan:YResolution/text()", namespaces={"scan": NS_SCAN})
    log.debug("Supported x-resolutions: %s", xResolutions)
    log.debug("Supported y-resolutions: %s", yResolutions)
    if args.resolution == '':
        resolution = max([value for value in xResolutions if value in yResolutions])
    else:
        resolution = args.resolution
    log.debug("Resolution: %s", resolution)
    if resolution not in xResolutions:
        error("Unsupported x-resolution '%s', supported: %s" % (resolution, xResolutions))
    if resolution not in yResolutions:
        error("Unsupported y-resolution '%s', supported: %s" % (resolution, yResolutions))

    # width/height
    maxWidth = first(tree.xpath("//scan:MaxWidth/text()", namespaces={"scan": NS_SCAN}), 2500)
    log.debug("Max width: %s", maxWidth)
    maxHeight = first(tree.xpath("//scan:MaxHeight/text()", namespaces={"scan": NS_SCAN}), 3500)
    log.debug("Max height: %s", maxHeight)

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
    if status != "Idle":
        error("Invalid scanner status: %s" % status)

    # start scanning
    startUrl = urljoin(args.url, "eSCL/ScanJobs")
    startReq = SCAN_REQUEST.replace("__FORMAT__", format).replace("__COLORMODE__", colorMode).replace("__RESOLUTION__", resolution).replace("__WIDTH__", maxWidth).replace("__HEIGHT__", maxHeight)
    if args.very_verbose:
        log.debug("Sending scan request to %s: %s", startUrl, startReq)
    else:
        log.debug("Sending scan request: %s", startUrl)
    resp = http.post(startUrl, startReq, headers={"Content-Type": "text/xml"})
    resp.raise_for_status()
    resultUrl = urljoin(resp.headers["Location"] + "/", "NextDocument") # status code is 201 so Requests won't follow Location

    # poll for the result every two seconds, give up after 10 failures
    counter = 0
    while True:
        time.sleep(2)
        log.debug("Polling: %s", resultUrl)
        resp = http.get(resultUrl)
        if resp.status_code == 200:
            log.debug("Received result")
            break
        counter += 1
        if counter >= MAX_POLL:
            error("Giving up after %d attempts to load result, try it manually later: curl -s %s > %s" % (MAX_POLL, resultUrl, filename))

    # write result
    log.debug("Writing: %s", filename)
    with open(filename, "wb") as f:
        f.write(resp.content)
    print(filename)

def first(a, default=None):
    return a[0] if a else default

def error(msg):
    print(msg)
    sys.exit(1)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="A little Python3 script for scanning via the eSCL protocol")
    ap.add_argument("-o", "--out", default="", help="output file name [default: " + DEF_NAME + "_<datetime>.<type>]")
    ap.add_argument("-t", "--type", default="jpg", help="desired resulting file type [default: %(default)s]", choices=["jpg", "pdf"])
    ap.add_argument("-r", "--resolution", default="", help="a single value for both X and Y resolution [default: max. available]")
    ap.add_argument("-c", "--color-mode", default="r24", help="RGB24 (r24) or Grayscale8 (g8) [default: %(default)s]", choices=["r24", "g8"])
    ap.add_argument("-v", "--verbose", action="store_true", help="Show debug output")
    ap.add_argument("-V", "--very-verbose", action="store_true", help="Show debug output and all data")
    ap.add_argument("url", help="URL of the scanner, incl. scheme and (if necessary) port")
    main(ap.parse_args())
