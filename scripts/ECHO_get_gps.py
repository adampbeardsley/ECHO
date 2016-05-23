'''

    Author: Jacob Burba

    ECHO_Get_GPS.py connects to a drone via MAVLink Micro Air Vehicle Communication Protocol and
    obtains the GPS positions of the drone in realtime.  A telemetry radio must be plugged in to the
    machine running this code to obtain a proper connection.  Additionally, ECHO_setup.sh must also
    be run prior to executing this code to ensure that the drone is broadcasting on two UDP channels,
    being 127.0.0.1:14550 and 127.0.0.1:14551.  The former is for communication with APM Planner
    while the latter channel is used for communication the machine running this code.

    When running this code, the user needs to pass a file name for the GPS positions and correspon-
    ing times to be written to.  The execution of this can be seen in the following example

                python ECHO_Get_GPS.py --gps_file=<output_filename> --trans=EW

    The generated output file can then be passed to ECHO_accumulate.py in which it will be stitched
    together with corresponding spectral data.

'''

import sys,os,optparse
import time
import numpy as np
from pymavlink import mavutil
#from astropy.time import Time

# Reading functions

# Time functions
def unix_to_gps(t):
    return Time(t,scale='utc',format='unix').gps

def gps_to_HMS(t):
    t = Time(t,scale='utc',format='gps')
    return t.iso.split(' ')[1]

# Position functions
def get_position(udp):
    loc = udp.location()
    return [loc.lat,loc.lng,loc.alt]

# Server API functions

# Plotting functions


o = optparse.OptionParser()
o.set_description('Takes raw APM/Orbcomm data and creates an interpolated, combined text file')
o.add_option('--gps_file',type=str,help='File name for output of GPS data')
o.add_option('--trans',type=str,help='Transmitting antenna polarization')
opts,args = o.parse_args(sys.argv[1:])


# Establish connection with Drone via UDP
udp = mavutil.mavudp('127.0.0.1:14551')

# Setup outfile
dt = 0.2 # time delay between GPS messages
date = time.strftime('%m_%d_%Y')
currtime = time.strftime('%H:%M:%S') # 24 Hr format
header = '# GPS Positions file for '+date+', '+currtime
if opts.trans:
    outfilename = opts.gps_file.split('.')[0]+'_'+opts.trans+'trans.txt'
    trans_pol = opts.trans
else:
    outfilename = opts.gps_file
    trans_pol = 'none'

# Write header, transmitter, and column format info to outfile
with open(outfilename,'wb') as outfile:
    outfile.write(header+'\n')
    outfile.write('# Transmitter polarization: '+trans_pol+'\n')
    outfile.write('# Col Format: Time [GPS s], Lat [deg], Lon [deg], Alt [m]\n')

try: # Continuously write time + position to outfile until close
    while True:
        loc = get_position(udp)
        query_time = unix_to_gps(time.time())
        if loc:
            loc_str = '%.2f,%.5f,%.5f,%.5f' %(query_time,loc[0],loc[1],loc[2])
            with open(outfilename,'ab') as outfile:
                outfile.write(loc_str+'\n')
        else:
            print 'No New GPS data at '+gps_to_HMS(query_time,'gps')+'s.'
            time.sleep(dt)
except KeyboardInterrupt:
    outfile.close()
    print '\n\n'+outfilename+' closed successfully'
    print 'Exiting...\n'
    sys.exit()
