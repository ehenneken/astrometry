#!/usr/bin/env python
# encoding: utf-8
"""
process_astrom.py :: given astrometry.net solution, convert to WCS

Created by August Muench on 2013-11-04.
Copyright (c) 2013 Smithsonian Astrophysical Observatory. All rights reserved.
"""

from __future__ import division  # confidence high
from __future__ import print_function  # i have to learn at some point

import os
import sys
import math
import datetime

import Image

import numpy as np

from astropy import wcs
from astropy.io import fits
from astropy.table import Table

s = 'process_astrom.py'

vkey = lambda v: str(v).upper()[0:8]  # FITS key validator


def id_img(p):
    """ stupid metadata extractor
    """
    try:
        im = Image.open(p)
        print(im.filename, im.format, im.size, im.mode)
    except IOError:
        pass


def parse_filename(f):
    """ 2010Ciel...72..113N-002-002.ppm
        [bibcode]-[page]-[figN]
    """
    values = f.split('-')
    values[-1] = values[-1].split(".")[0]
    return dict(zip(("bibcode", "page", "figN"), values))


def parse_img(p):
    """open and extract useful information from the image into a dictionary
       also:
            * Flatten Image to GreyScale (as it should be in this use case)
            *
    """
    try:
        img = Image.open(p)
        xs, ys = img.size
        imgL = img.convert("F")
        return {
            "im": imgL,
            "xs": xs,
            "ys": ys,
            "format": img.format
        }
    except:
        return {}


def parse_txt(t):
    """process .txt files returned by astrometry.net to extract some WCS
    related quantities.

    Example: 2010Ciel...72..113N, Page 2, Figure 2 (Pleiades)

        testing image: 2010Ciel...72..113N-002-002.ppm
        #non-inverted image solved without SIMBAD coordinates in 613.357455015 seconds
        (56.7, 24.15)
        81.4539 x 59.1175 arcminutes
        Field rotation angle: up is -179.411 degrees E of N

    Return: (dictionary)
        "solved":   logical,
        "ra":       decimal degrees,
        "dec":      decimal degress,
        "inverted": inverted,
        "bibcode":  ADS bibcode as text,
        "xs":       X size in pixels,
        "ys":       Y size in pixels,
        "rt":       Rotation angle extracted,
        "txt":      line by line data as string lists [5 lines]

    """

    # tiny converter [arcseconds per unit]
    u = {
        "arcseconds": 3600.,
        "arcminutes": 60.,
        "degrees": 1.
    }

    with open(t) as f:
        data = f.readlines()
        data = [d.strip() for d in data]
        if len(data) == 3:
            return {"solved": False}
        pf = parse_filename(data[0].split(" ")[-1])
        bibcode, figN, page = [pf.get(i) for i in ['bibcode', 'figN', 'page']]
        #bibcode = data[0][15:34]
        inverted = data[1].split(" ")[0][1:]
        inverted = inverted == 'inverted' and True or False
        ra = float(data[2].split(" ")[0][1:-1])
        dec = float(data[2].split(" ")[1][0:-1])

        xs = float(data[3].split(" ")[0])
        ys = float(data[3].split(" ")[2])
        us = data[3].split(" ")[3]
        if us not in u:
            raise  # units aren't preordained.
        else:
            xs, ys = map(lambda x: x / u[us], (xs, ys))

        rt = float(data[4].split(" ")[5])

    return {
        "solved": True,
        "ra": ra,
        "dec": dec,
        "inverted": inverted,
        "bibcode": bibcode,
        "figN": figN,
        "page": page,
        "xs": xs,
        "ys": ys,
        "rt": rt,
        "txt": data,
    }


def cd2cd(cdelt1, cdelt2, crota2, ret="cd"):
    """
    Yes, I just wrote a program to do this.
    [
      ["CD1_1", "CD1_2"],
      ["CD2_1", "CD2_2"]
    ]
    ==
    [
       [(0,0), (0,1)],
       [(1,0), (1,1)]
    ]
    i_j
    axis, pixel
    cdelt_i = row major

    """
    cd = np.zeros((2, 2))
    pc = np.zeros((2, 2))
    crota2 = math.radians(crota2)

    cd[0, 0] = cdelt1 * math.cos(crota2)
    cd[0, 1] = cdelt1 * math.sin(crota2)
    cd[1, 0] = -cdelt2 * math.sin(crota2)
    cd[1, 1] = cdelt2 * math.cos(crota2)

    pc[0, 0] = cd[0, 0] / cdelt1
    pc[0, 1] = cd[0, 1] / cdelt1
    pc[1, 0] = cd[1, 0] / cdelt2
    pc[1, 1] = cd[1, 1] / cdelt2

    if ret == "cd":
        return cd
    elif ret == "pc":
        return pc


def build_hdr(img, txt):
    """ builder of hdr from input files
    """
    # converters
    ldpix = lambda x: math.floor(x / 2)

    w = wcs.WCS(naxis=2)

    # where does the NAXISn pixel number get encoded?
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]  # assumed
    w.wcs.cunit = ['deg', 'deg']  # assumed

    w.wcs.crpix = [ldpix(l) for l in (img['xs'], img['ys'])]  # assume center
    w.wcs.crval = [txt['ra'], txt['dec']]

    # the pixel scale is the angular size in degrees / pixels in X, Y
    # eventually I have to figure out the CROTAn/rotation axis.
    # there is probably an axis flip in here too (PIL Image => FITS)

    cdelt1, cdelt2 = (txt['xs'] / img['xs'], txt['ys'] / img['ys'])
    crota2 = txt['rt']
    # for k,v in dict(zip(
    #     ("cdelt1", "cdelt2", "crota2"), (cdelt1, cdelt2, crota2)
    #     )).items():
    #     print('{0:10} ==> {1:10f}'.format(k, v))

    #w.wcs.cd = cd2cd(cdelt1, cdelt2, crota2, ret="cd")
    w.wcs.pc = cd2cd(cdelt1, cdelt2, crota2, ret="pc")
    w.wcs.cdelt = [cdelt1, cdelt2]

    hdr = w.to_header()

    # add documentation from txt file
    docs = {"REFERENC": (txt['bibcode'], "ADS Bibcode"),
            "REF_FIGN": (txt['figN'], "Figure Number"),
            "REF_PAGE": (txt['page'], "Page Number"),
            "CROTAX": (txt['rt'], "CROTA2 (hidden)")}
    hdr = document(hdr, docs=docs)
    hdr = comments(hdr, stuff={'Original Header': txt['txt']})

    return hdr


def write_fits(img, hdr, out="test.fits", ret=False):
    """ convert the image array to fits data; write out fits
    """
    # as dumb as it looks for now.
    data = np.asarray(img['im']).copy()  # transfer memory from PIL to np
    hdu = fits.PrimaryHDU(data, header=hdr)
    hdu.writeto(out, clobber=True)

    if ret:
        return hdu, data  # send back the converted image
    else:
        return None


def lsp(l, s, p=[]):
    """ yes. yes, I did write this
    """
    if len(l) <= s:
        p.append(l)
        return p
    else:
        p.append(l[0:s])
        return lsp(l[s:], s, p)


def fits2day():
    """ Create a valid FITS data string for today.
    YYYY-MM-DDThh:mm:ss[.sss...]
    """
    tr = 19
    a = "{!s}".format(datetime.datetime.today()).strip(" ")

    return "T".join(a.split())[0:tr]


def document(hdr, docs={"DATE": (fits2day(), "Creation date (apx)")}):
    """ add documentation keys to headers.
    defaults to add creator DATE. if not specified.
    """
    if "DATE" not in docs:
        docs['DATE'] = (fits2day(), "Creation date (apx)")

    for k, v in docs.items():
        hdr[vkey(k)] = v

    return hdr


def comments(hdr, stuff={"Written by": s}):
    """ function to add comments to FITS header.
    Clips and block quotes comments to make them fit in the
      FITS 80 char line length limit.
    """
    hdr['COMMENT'] = "-" * 70
    if "Written by" not in stuff.keys():
        stuff["Written by"] = s

    for k, v in stuff.items():
        if not isinstance(v, (list, dict, tuple,)):
            hdr['COMMENT'] = "{0} {1}".format(k, v)
        else:
            hdr['COMMENT'] = k
            t = "  "
            nt = 80 - 10 * len(t)
            for l in v:
                ll = lsp(l, nt, [])
                for i, lll in enumerate(ll):
                    hdr['COMMENT'] = '|{0} {1}'.format(t * (i + 1), lll)

    return hdr


def tabulate(t):
    # find a good header
    h = 1
    # while h:
    #     if t[]


def test():
    """ a real test
    """
    return


def run(f):
    """ postprocess an astrometry.net files

    """
    # check files exists
    r = ".".join(f.split(".")[:-1])
    p, t = [r + "." + x for x in ('png', 'txt')]
    s = sum(map(os.path.exists, (p, t)))
    if s < 2:
        print('{0} input files are missing'.format(2 - s))
        return {}

    txt = parse_txt(t)
    img = parse_img(p)

    hdr = txt['solved'] and build_hdr(img, txt) or None

    return {'hdr': hdr, 'txt': txt, 'img': img}


def main():
    flist = [f for f in os.listdir(".") if (f[-3:] == "png")]
    p = map(run, flist)


if __name__ == '__main__':
    main()
