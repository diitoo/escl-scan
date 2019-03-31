# escl-scan
A little Python3 script for scanning via the _eSCL_ protocol. Supported features:
- JPG and PDF
- Color and grayscale
- Multiple resolutions
- Multiple paper sizes

# Usage
Invoke the script like this to see all possible options:
```
python3 escl-scan.py -h
```

# Hint
Since the scanner's URL isn't likely to change, you can hard-code it in a helper script for convenience. The same is true for default values of other options.
For example, if the scanner's IP is 192.168.1.8 and you want to scan A4 paper by default:
```bash
#!/bin/bash
python3 ~/<THE-PATH>/escl-scan.py -s a4 "$@" http://192.168.1.8
```
Invoking this helper script without any arguments triggers scanning of size A4 in color with the highest available resolution and puts the resulting JPG into the current directory.
Invoking it with just `-t pdf` does the same for a PDF file.

# Background
Using _hplip-3.19.3_ (and some older versions) I was only able to **print** on the _HP LaserJet MFP M28w_, but all attempts to **scan** (via `hp-scan` and `xsane` over USB and WiFi) resulted in `SANE: Error during device I/O (code=9)`. Even though the M28w is supposed to be fully supported on linux.

This little script is a work-around until that error is fixed. It uses _eSCL_, which is _HP_'s and _Apple_'s scan protocol, to initiate a scan request over WiFi.

I cannot possibly tell what the system requirements are, except for the obvious Python3, but you will probably want to install _hplip_ (and the corresponding _hplip-plugin_) anyway for printing.
