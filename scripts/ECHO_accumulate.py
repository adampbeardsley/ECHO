'''

    Author: Jacob Burba

    ECHO_accumulate.py reads in a radio spectrum from the Signal Hound BB60A spectrum analyzer
    with a time in UTC at which the spectrum was obtained.  This time is used to query the Flask server
    created in ECHO_server.py to obtain the interpolated GPS position of the drone at the query time.
    This GPS positional information is then combined with the query time and radio spectrum and
    written to a file of the form 'accumulated_<date>_<time>.txt' which contains all necessary info for
    ECHO_plot.py.  The accumulated file has four lines in the header which are as follows

        # Accumulated data for <date>, <time>
        # Column Format: 1 Time [GPS s], 2 Lat [deg], 3 Lon [deg], 4 Rel Alt [m], 5: Radio Spectrum
        # lat0,lon0: <latitude of antenna>, <longitude of antenna under test>
        # Freqs: <list of frequencies in corresponding columns of radio spectrum>

    The following rows of data then contain the data specified in the column format comma delimited.

    When calling ECHO_accumulate.py, the user MUST specify all of the following flags

        --host : host IP address of ECHO_server.py.  DO NOT pass port number as the default port
                    5000 is assumed.
        --spec_file : filename for spectral data generated by get_sh_spectra
        --lat0 : latitude of antenna under test
        --lon0 : longitude of antenna under test

    An example call can be seen as follows

    python ECHO_accumulate.py --host 10.1.1.1 --spec_file <sh spectra file> --lat0 <lat> --lon0 <lon>

'''


import urllib2,optparse,sys,json
import numpy as np
import time

from astropy.time import Time
from ECHO_read_utils import get_data
from ECHO_time_utils import unix_to_gps


o = optparse.OptionParser()
o.set_description('ECHO_accumulate queries ground station server for \
                          interpolated GPS positions of the drone and combines \
                          them with spectral data into one output file.')
o.add_option('--host',type=str,default='10.1.1.1',
                    help='Host for server (string).  Default is 10.1.1.1')
o.add_option('--spec_file',type=str,help='Radio spectrum file')
o.add_option('--gps_file',type=str,help='GPS position file')
o.add_option('--acc_file',type=str,help='Accumulated output file')
o.add_option('--lat0',type=str,help='Latitude of antenna under test')
o.add_option('--lon0',type=str,help='Longitude of antenna under test')
o.add_option('--freq',type=float,default=137.554,
                    help='Frequency of importance')
o.add_option('--realtime',action='store_true',
                    help='Specify realtime accumulation of data')
opts,args = o.parse_args(sys.argv[1:])


dt = 0.3 # Time delay between queries of ECHO_server.py
last_row_index = 0 # Index for SH time queries
freq_chan = 0 # Index in spectrum of Valon synth peak freq
freqs = [] # Store frequencies in SH spectrum
add_chans = 10 # Number of bins left/right of freq_chan to keep


'''####################################################
#                                                   REALTIME                                                     #
####################################################'''

if opts.realtime:
    # Check for valid gps_file
    if not opts.gps_file:
        print '\nPlease pass a valid GPS position file (--gps_file)...\n'
        sys.exit()

    # Check for valid spec_file
    if not opts.spec_file:
        print '\nPlease pass a valid spectrum file (--spec_file)...\n'
        sys.exit()

    # Check for valid acc_file
    if not opts.acc_file:
        print '\nPlease pass a valid accumulated file (--acc_file)...\n'
        sys.exit()

    # Check for latitude and longitude of antenna under test
    if not (opts.lat0 and opts.lon0):
        print '\nLatitude (--lat0) and Longitude (--lon0) required...\n'
        sys.exit()

    start_timestr = time.strftime('%H:%M:%S') # Current time in Hours:Min:Sec
    start_datestr = time.strftime('%d_%m_%Y') # Current date in Day_Month_Yr
    #outfile_str = 'accumulated_'+start_datestr+'_'+start_timestr+'.txt'
    #outfile_str = 'accumulated_'+opts.version+'.txt'
    outfile_str = opts.acc_file

    # Header information for output file
    headstr = '# Accumulated data for '+start_datestr+', '+start_timestr
    colfmtstr = '# Column Format: 1 Time [GPS s], 2 Lat [deg], 3 Lon [deg],\
                            4 Rel Alt [m], 5: Radio Spectrum'
    latlonstr = '# lat0,lon0: %s,%s' %(opts.lat0,opts.lon0)
    with open(outfile_str,'ab') as outfile:
        # Write header information to output file
        outfile.write(headstr+'\n'+colfmtstr+'\n'+latlonstr+'\n')

    # Read in initial SH data
    spec_times,spec_raw,freqs,freq_chan = get_data(opts.spec_file,filetype='sh',\
                                                                freqs=freqs,freq=opts.freq,freq_chan=freq_chan)
    #print 'Read in %d lines from $s' %(spec_times.shape[0],opts.spec_file)
    with open(outfile_str,'ab') as outfile:
        # Write frequencies to output file for indexing in ECHO_plot.py
        outfile.write('# Freqs: '+','.join(map(str,freqs))+'\n')

    # Read in SH data and query ECHO_server.py
    curr_size = spec_times.shape[0]
    while True:
        if not spec_times.shape[0] == curr_size:
            curr_size = spec_times.shape[0]
        while last_row_index < spec_times.shape[0]:
            qtime = unix_to_gps(spec_times[last_row_index])
            fileo = urllib2.urlopen('http://'+opts.host+':5000/ECHO/lms/v1.0/pos/'+str(qtime))
            pos = json.loads(fileo.read())
            if not pos['lat'] == -1:
                outstr = str(qtime)+','+str(pos['lat'])+','+str(pos['lon'])+','+\
                             str(pos['alt'])+','+','.join(map(str,spec_raw[last_row_index,:]))
                # Check that output string has the correct number of columns
                if len(outstr.split(',')) == 24:
                    with open(outfile_str,'ab') as outfile:
                        outfile.write(outstr+'\n')
            else:
                with open(outfile_str,'ab') as outfile:
                    # Print -1 for all entries with no valid GPS data
                    outfile.write(str(qtime)+','+','.join(map(str,[-1]*23))+'\n')

        # Update row counter and wait for new data
        last_row_index += 1
        time.sleep(dt)

        # Read in new spectrum data
        spec_times,spec_raw,freqs,freq_chan = get_data(opts.spec_file,filetype='sh',\
                                                                    freqs=freqs,freq=opts.freq,freq_chan=freq_chan)
        #print 'Read in %d lines from $s' %(spec_times.shape[0],opts.spec_file)


'''####################################################
#                                                NOT REALTIME                                                 #
####################################################'''


'''
else:
    # do stuff not realtime
    spec_times,spec_raw = get_spec(opts.spec_file)
    start_time = spec_times[0,0]
    start_timestr = time.strftime('%H:%M:%S') # Current time in Hours:Min:Sec
    start_datestr = time.strftime('%d_%m_%Y') # Current date in Day_Month_Yr
    outfile_str = 'accumulated_'+start_datestr+'_'+start_timestr+'.txt'

    # Header information for output file
    headstr = '# Accumulated data for '+start_datestr+', '+start_timestr
    colfmtstr = '# Column Format: 1 Time [GPS s], 2 Lat [deg], 3 Lon [deg], 4 Rel Alt [m], 5: Radio Spectrum'
    latlonstr = '# lat0,lon0: %s,%s' %(opts.lat0,opts.lon0)

'''
