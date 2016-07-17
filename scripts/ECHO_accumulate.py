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

o.add_option('--spec_file',type=str,
    help='Radio spectrum file. For multiple files specify --isList')
o.add_option('--gps_file',type=str,
    help='GPS position file. For multiple files specify --isList')
o.add_option('--apm_file',type=str,
    help='APM log file(s). For multiple files specify --isList')
o.add_option('--acc_file',type=str,
    help='Accumulated output file')
o.add_option('--start_stop',action='store_true',
    help='If true, data filtered with flight start/stop times')
o.add_option('--waypts',action='store_true',
    help='If true, data filtered around waypoint times')
#o.add_option('--isList',action='store_true',
#    help='Specify if passing several APM/spec files for reading')
o.add_option('--lat0',type=str,
    help='Latitude of antenna under test')
o.add_option('--lon0',type=str,
    help='Longitude of antenna under test')
o.add_option('--freq',type=float,default=137.500,
    help='Frequency of importance')
o.add_option('--width',type=int,default=500,
    help='Keep channels within 0.005*width [MHz] of --freq')
o.add_option('--realtime',action='store_true',
    help='Specify realtime accumulation of data')
o.add_option('--host',type=str,default='10.1.1.1',
    help='Host for server (string).  Default is 10.1.1.1')
o.add_option('--nfft',type=int,
    help='Number of FFT bins in Signal Hound spectra')

opts,args = o.parse_args(sys.argv[1:])


# Check for valid spec_file
if not opts.spec_file:
   print '\nPlease pass a valid spectrum file (--spec_file)...\n'
   sys.exit()

# Check for latitude and longitude of antenna under test
if not (opts.lat0 and opts.lon0):
   print '\nLatitude (--lat0) and Longitude (--lon0) required...\n'
   sys.exit()


DELAY_TIME = 0.3 # Time delay between queries of ECHO_server.py
last_row_index = 0 # Index for SH time queries
freq_chan = 0 # Index in spectrum of Valon synth peak freq
freqs = [] # Store frequencies in SH spectrum

print ' '
# Read in initial SH data
spec_times,spec_raw,freqs,freq_chan = get_data(opts.spec_file,
                                               filetype='sh',
                                               freqs=freqs,
                                               freq=opts.freq,
                                               freq_chan=freq_chan,
                                               width=opts.width,
                                               nfft=opts.nfft)#,
                                               #isList=opts.isList)
print 'Read in %s spectra spanning %s frequencies\n' %(spec_times.shape[0],
                                                         freqs.shape[0])


# Get date/time info for file naming
date_time = spec_times[0].iso.split(' ')
time_str = '-'.join(date_time[-1].split(':')).split('.')[0]
#outfile_str = 'acc_'+date_time[0]+'_'+time_str+'.txt'
outfile_str = opts.acc_file

# Header information for output file
headstr = '# Accumulated data for '+','.join(date_time)
colfmtstr = '# Column Format:Time [GPS s],Lat [deg],Lon [deg],Rel Alt [m],Radio Spectrum'
latlonstr = '# lat0,lon0: %s,%s' %(opts.lat0,opts.lon0)
freqstr =  '# Freqs: '+','.join(map(str,freqs))

# Create accumulated output file for writing
with open(outfile_str,'wb') as outfile:
    # Write header information to output file
    outfile.write(headstr+'\n'+colfmtstr+'\n'+latlonstr+'\n'+freqstr+'\n')


if opts.realtime:

    '''####################################################
    #                      REALTIME                       #
    ####################################################'''

    # Check for valid gps_file
    if not opts.gps_file:
        print '\nPlease pass valid file(s) with GPS positions with --gps_file...\n'
        sys.exit()

    # Read in SH data and query ECHO_server.py
    last_row_index = 0 # Index for SH time queries
    while True:
        while last_row_index < spec_times.shape[0]:
            qtime = spec_times.gps[last_row_index]
            fileo = urllib2.urlopen('http://'+opts.host+':5000/ECHO/lms/v1.0/pos/'+str(qtime))
            try:
                pos = json.loads(fileo.read())
                outstr = str(qtime)+','+\
                         str(pos['lat'])+','+\
                         str(pos['lon'])+','+\
                         str(pos['alt'])+','+\
                         ','.join(map(str,spec_raw[last_row_index,:]))
                # Check that output string has the correct number of columns
                if len(outstr.split(',')) == (len(freqs)+4):
                    with open(outfile_str,'ab') as outfile:
                        outfile.write(outstr+'\n')
            except(ValueError):
                pass
            # Update row counter and wait for new data
            last_row_index += 1
            time.sleep(DELAY_TIME)

        # Read in new spectrum data
        spec_times,spec_raw,freqs,freq_chan = get_data(opts.spec_file,
                                                       filetype='sh',
                                                       freqs=freqs,
                                                       freq=opts.freq,
                                                       freq_chan=freq_chan,
                                                       width=opts.width,
                                                       nfft=opts.nfft)





else:

    '''####################################################
    #                   POST-PROCESSING                   #
    ####################################################'''

    from ECHO_read_utils import get_filter_times
    from ECHO_position_utils import interp_pos
    from ECHO_time_utils import flight_time_filter,waypt_time_filter

    if opts.apm_file:
        # Read in data from APM file(s)
        times,lats,lons,alts = get_data(opts.apm_file,
                                        filetype='apm')#,
                                        #isList=opts.isList)

    elif opts.gps_file:
        # Read in data from ECHO GPS file(s)
        times,lats,lons,alts = get_data(opts.gps_file,
                                            filetype='gps')#,
                                            #isList=opts.isList)

    if not opts.apm_file and not opts.gps_file:
        print '\nPlease pass valid file(s) with GPS positions with --gps_file...\n'
        sys.exit()

    print 'Read in %s GPS positions' %lats.shape[0]

    minTime = times.gps.min()
    maxTime = times.gps.max()

    # Left off here !!!
    #print "Before time filter: ",spec_times.shape
    specInds = np.where(np.logical_and(spec_times.gps>minTime,
                                       spec_times.gps<maxTime))[0]
    spec_times,spec_raw = spec_times[specInds],spec_raw[specInds]
    #print "After time filter: ",spec_times.shape


    # Interpolate GPS positions
    print '\nInterpolating...'
    start = time.time()
    latsi,lonsi,altsi = interp_pos(times.gps,lats,lons,alts)
    stop = time.time()
    print 'Interpolation finished in %.1e seconds' %(stop-start)
    latsi = latsi(spec_times.gps)
    lonsi = lonsi(spec_times.gps)
    altsi = altsi(spec_times.gps)


    # Zip everything together for start/stop and waypt filtering
    spec_times = np.expand_dims(spec_times.gps,axis=1)
    latsi = np.expand_dims(latsi,axis=1)
    lonsi = np.expand_dims(lonsi,axis=1)
    altsi = np.expand_dims(altsi,axis=1)
    all_Data = np.concatenate((spec_times,latsi,lonsi,altsi,spec_raw),
                               axis=1)
    print '\nZipped data shape: '+str(all_Data.shape)


    if opts.start_stop:
        if opts.apm_file is None:
            print '\nAPM file (glob) needed for start/stop filtering.'
            print 'Exiting...\n'
            sys.exit()

        if opts.waypts:
            start_stop_times,waypt_times = get_filter_times(opts.apm_file,
                                                            waypts=True)
        else:
            start_stop_times = get_filter_times(opts.apm_file)

        start_stop_inds = flight_time_filter(start_stop_times,
                                            all_Data[:,0])
        print '\nBefore start/stop time filter: %s' %all_Data.shape[0]
        all_Data = all_Data[start_stop_inds]
        print 'After start/stop time filter: %s' %all_Data.shape[0]

        if opts.waypts:
            waypt_inds = waypt_time_filter(waypt_times,
                                           all_Data[:,0])
            print '\nBefore waypoint filter: %s' %all_Data.shape[0]
            all_Data = all_Data[waypt_inds]
            print 'After waypoint filter: %s' %all_Data.shape[0]

    # Write accumulated data to output file
    print '\nWriting to %s...' %outfile_str
    for k in range(all_Data.shape[0]):
        '''
            Error thrown here.
            ','.join expects string but gets float.  Wtf?
        '''
        outstr = ','.join(map(str,all_Data[k,:]))
        if len(outstr.split(',')) == (len(freqs)+4):
            with open(outfile_str,'ab') as outfile:
                outfile.write(outstr+'\n')
    print '%s closed successfully\n' %outfile_str