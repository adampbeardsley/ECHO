#!/usr/bin/env python
# -*- coding: utf-8 -*-
# 
# Copyright 2018 <+YOU OR YOUR COMPANY+>.
# 
# This is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
# 
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this software; see the file COPYING.  If not, write to
# the Free Software Foundation, Inc., 51 Franklin Street,
# Boston, MA 02110-1301, USA.
# 

import numpy
from gnuradio import gr
from numpy import complex64, float32, int32

_type_to_type = {
  complex: complex64,
  float: float32,
  int: int32,
}


class welch(gr.decim_block):
    """
    docstring for block welch
    """
    def __init__(self, dtype, length, window, overlap):
        gr.decim_block.__init__(self,
            name="welch",
            in_sig=[_type_to_type[dtype]],
            out_sig=[(_type_to_type[dtype], length)],decim=length)

    def work(self, input_items, output_items):
        in0 = input_items[0]
        out = output_items[0]
        # <+signal processing here+>
        return len(output_items[0])
