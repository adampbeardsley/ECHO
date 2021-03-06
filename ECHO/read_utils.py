from __future__ import print_function
from __future__ import absolute_import
import numpy as np,healpy as hp
import sys
import glob
from astropy.time import Time

from scipy.interpolate import interp1d
from .time_utils import flight_time_filter,waypt_time_filter, DatetimetoUnix
from distutils.version import StrictVersion
import pyulog.core as pyu
import pyulog.ulog2csv as pyucsv
from pyuvdata import UVBeam
from pyuvdata.data import DATA_PATH
import h5py

SEC_PER_WEEK = 604800
APMLOG_SEC_PER_TICK = 1.0e-6
def dB(x):
    return 10*np.log10(x)
def dB2(x): #this is the definition of dB for Voltages
    return 20*np.log10(x)

def concat_times(Ts):
    "input a list of astropy time vectors"
    "return a single concatenated time vector"
    return Time(np.concatenate([t.gps for t in Ts]),format='gps')
def read_map(filename):
    M = np.ma.array(hp.read_map(filename),fill_value=hp.UNSEEN)
    M = np.ma.masked_where(hp.UNSEEN==M,M)
    M.fill_value = hp.UNSEEN
    return M
def write_map(filename,M):
    "write out a masked healpix map with the correct fill values"
    M.set_fill_value(hp.UNSEEN)
    hp.write_map(filename,M.filled())
    return 0
def apm_version(filename):
    """
    Read an apm file and try to detirmine the version of the firmware which wrote it
    """
    lines = open(filename).readlines()
    for line in lines:
        #in 3.3.3 and higher the first MSG line gives the version
        if line.startswith('MSG'):
            try:
                version = line.split('V')[1].split()[0]
                return version
            except(IndexError):
                #big assumption here, that if the version is unlisted its 3.3.2
                #if you know a better way to tell the version in old logs
                #  please put it here
                return '3.3.2'
    return '0.0.1'
def read_apm_logs(apm_files):
    """
    input:
    apm_files: a list of apm logs
    waypoints: range of waypoints to include [1,-1] will get everything between first and last
    return: positiontimes,positions,angletimes,angles
    times are astropy.time.Time vectors
    positions are (3,ntimes) in order lat,lon,alt
    angles are (1,ntimes) with only yaw (todo, add roll,pitch)
    """
    #check the firmware version
    versions = [apm_version(f) for f in apm_files]
    if len(set(versions))>1:
        for f,v in zip(apm_files,versions):
            print((f,v))
        raise ValueError
    postimes=[]
    angletimes=[]
    positions = []
    angles = []
    CMD_times = []
    CMD_nums = []
    for apm_file in apm_files:
        file_postimes,file_positions,file_angletimes,file_angles,file_cmdtimes,file_cmds = read_apm_log(apm_file)
        positions.append(file_positions)
        angles.append(file_angles)
        postimes.append(file_postimes)
        angletimes.append(file_angletimes)
        CMD_times.append(file_cmdtimes)
        CMD_nums.append(file_cmds)
    angles = np.concatenate(angles,axis=1)
    positions = np.concatenate(positions,axis=1)
    postimes = concat_times(postimes)
    angletimes = concat_times(angletimes)
    CMD_times = concat_times(CMD_times)
    CMD_nums = np.concatenate(CMD_nums)
    return postimes,positions,angletimes,angles,CMD_times,CMD_nums
def read_apm_log_3_3_2(apm_file):
    apm_timescale = 1000.
    startTime = -1
    lats,lons,alts,weektimes,ATT_times,yaws = [],[],[],[],[],[]
    CMD_times,CMD_nums = [],[]
    isAuto = False
    paststartwaypoint = False
    lines = open(apm_file).readlines()
    if len(lines) == 0: return None,None,None,None,None,None
    for line in lines:
        """
        http://ardupilot.org/copter/docs/common-downloading-and-analyzing-data-logs-in-mission-planner.html
        Mode (0=Stabilize, 1=Acro, 2=AltHold, 3=Auto, 4=Guided, 5=Loiter, 6=RTL, 7=Circle, 8=Position, 9=Land, 10=OF_Loiter, 11=Drift, 13=Sport, 14=Flip, 15=AutoTune, 16=PosHold, 17=Brake)
        """
        #only collect data in auto mode
        if line.startswith('MODE'):
            isAuto = int(line.split(',')[1])==3
        if not isAuto:
            #if we go out of auto reset this check
            # and skip data
            paststartwaypoint = False
            continue
        if line.startswith('CMD') and not paststartwaypoint:
            cmd = int(line.split(',')[3].strip())
            #only collect data once we hit the first mapping waypoint
            # which is when waypoint 3 is commanded
            paststartwaypoint = cmd>3
        if not paststartwaypoint:continue
        #checks are complete, any lines now are fair game
        if line.startswith('GPS'):
            if startTime<0:
                startTime = float(line.split(',')[-1])
            lats.append(map(float,line.split(',')[6:7]))
            lons.append(map(float,line.split(',')[7:8]))
            alts.append(map(float,line.split(',')[8:9]))
            weektimes.append(map(float,line.split(',')[2:4])) #ms and week number
        if line.startswith('ATT'):
            ATT_times.append(map(float,[line.split(',')[1].strip(' ')]))
            yaws.append(map(float,[line.split(',')[7].strip(' ')]))
        if line.startswith('CMD'):
            CMD_times.append(float(line.split(',')[1].strip()))
            CMD_nums.append(cmd)
    weektimes = np.array(weektimes)
    apm_times = weektimes[:,1]*SEC_PER_WEEK+weektimes[:,0]/1000.
    apm_times = Time(apm_times,format='gps',scale='utc')
    ATT_times = np.array(ATT_times).squeeze()
    ATTGPSseconds = ATT_times/apm_timescale - startTime/apm_timescale+apm_times.gps[0]
    ATT_times = Time(ATTGPSseconds, format = 'gps',scale='utc')
    CMD_times = np.array(CMD_times)
    CMDgpsseconds = CMD_times/apm_timescale - startTime/apm_timescale+apm_times.gps[0]
    CMD_times = Time(CMDgpsseconds, format='gps',scale='utc')
    lats = np.array(lats).squeeze()
    lons = np.array(lons).squeeze()
    alts = np.array(alts).squeeze()
    yaws = np.array(yaws).squeeze()
    return apm_times,[lats,lons,alts],ATT_times,[yaws],CMD_times,CMD_nums
def read_apm_log_3_3_3(apm_file):
    apm_timescale = 1.e6
    startTime = -1
    lats,lons,alts,weektimes,ATT_times,yaws = [],[],[],[],[],[]
    CMD_times,CMD_nums = [],[]
    isAuto = False
    paststartwaypoint = False
    start = False
    lines = open(apm_file).readlines()
    if len(lines) == 0: return None,None,None,None,None,None
    for i,line in enumerate(lines):
        """
        http://ardupilot.org/copter/docs/common-downloading-and-analyzing-data-logs-in-mission-planner.html
        Mode (0=Stabilize, 1=Acro, 2=AltHold, 3=Auto, 4=Guided, 5=Loiter, 6=RTL, 7=Circle, 8=Position, 9=Land, 10=OF_Loiter, 11=Drift, 13=Sport, 14=Flip, 15=AutoTune, 16=PosHold, 17=Brake)
        """
        if line.startswith('STRT'):
            start = True
            continue
        elif not start:
            continue
        #only collect data in auto mode
        if line.startswith('MODE'):
            isAuto = int(line.split(',')[3])==3
            continue
        if not isAuto:
            #if we go out of auto reset this check
            # and skip data
            paststartwaypoint = False
            continue
        if line.startswith('CMD') and isAuto:
            cmd = int(line.split(',')[3].strip())
            #only collect data once we hit the first mapping waypoint
            # which is when waypoint 3 is commanded
            paststartwaypoint = cmd>3
        if not paststartwaypoint:continue
        #checks are complete, any lines now are fair game
        if line.startswith('GPS'):
            if startTime<0:
                startTime = float(line.split(',')[-1])
            lats.append(float(line.split(',')[7].strip()))
            lons.append(float(line.split(',')[8].strip()))
            alts.append(float(line.split(',')[9].strip()))
            weektimes.append(map(float,line.split(',')[3:5])) #ms and week number
        if line.startswith('ATT'):
            ATT_times.append(map(float,[line.split(',')[1].strip(' ')]))
            yaws.append(map(float,[line.split(',')[7].strip(' ')]))
        if line.startswith('CMD'):
            CMD_times.append(float(line.split(',')[1].strip()))
            CMD_nums.append(cmd)
    weektimes = np.array(weektimes)
    apm_times = weektimes[:,1]*SEC_PER_WEEK+weektimes[:,0]/1000.
    apm_times = Time(apm_times,format='gps',scale='utc')
    ATT_times = np.array(ATT_times).squeeze()
    ATTGPSseconds = ATT_times/apm_timescale - startTime/apm_timescale+apm_times.gps[0]
    ATT_times = Time(ATTGPSseconds, format = 'gps',scale='utc')
    CMD_times = np.array(CMD_times)
    CMDgpsseconds = CMD_times/apm_timescale - startTime/apm_timescale+apm_times.gps[0]
    CMD_times = Time(CMDgpsseconds, format='gps',scale='utc')
    lats = np.array(lats).squeeze()
    lons = np.array(lons).squeeze()
    alts = np.array(alts).squeeze()
    yaws = np.array(yaws).squeeze()
    return apm_times,[lats,lons,alts],ATT_times,[yaws],CMD_times,CMD_nums
def read_apm_log(apm_file):
    "read in an apm log file"
    "return [time,lat,lon,alts],[time,yaws],CMDtimes,CMDnums"
    "time objects are astropy.time.Time objects"
    "only returns data in auto mode "
    " and after waypoint #2 is commanded"
    version = apm_version(apm_file)
    if StrictVersion(version)<StrictVersion('3.3.3'):
        return read_apm_log_3_3_2(apm_file)
    if StrictVersion(version)>=StrictVersion('3.3.3'):
        return read_apm_log_3_3_3(apm_file)



def read_echo_spectrum(infiles):
    """
    input:
    filenames: list of string paths pointing to files generated by get_sh_spectra
    (or similar)

    return: times,frequencies,spectrumwaterfall
    times: astropy.time.Time object
    frequencies: in MHz
    spectrumwaterfall: shape=(len(times),len(frequencies))
    """
    spec_times = []
    spec_raw = []
    for i,spec_file in enumerate(infiles):
        #print 'Reading in %s...' %spec_file
        lines = open(spec_file).readlines()
        freqs = np.array(map(float,lines[1].rstrip('\n').split(',')[1:]))
        if len(lines) == 0:continue
        for line in lines[2:]:
            if line.startswith('#'):
                continue
            line = line.strip().split(',')
            if len(line)!=(len(freqs)+1):continue #skip lines with missing data
            spec_times.append(float(line[0]))
            spec_raw.append(map(float,line[1:]))
    spec_times = Time(spec_times,format='unix')
    spec_raw = np.array(spec_raw)
    freqs = np.array(freqs).squeeze()
    return spec_times,freqs,spec_raw,
#from orbcomm_compile.py S-NS[7:12], N-NS[13:18], S-EW[14:19], N-EW[20:25]'
getsatfourchanNG_channels = {'S_NS':np.arange(0,6),
                             'N_NS':np.arange(6,12),
                             'S_EW':np.arange(12,18),
                             'N_EW':np.arange(18,24)}
def read_orbcomm_spectrum(infiles,ant,pol):
    """
    input: filenames,ant,pol
    filenames: list of string paths pointing to files generated by Neben, getsatfourchanNG
    ant: 'N' or 'S'
    pol: 'EW' or 'NS'

    return: times,frequencies,spectrumwaterfall
    times: astropy.time.Time object
    frequencies: in MHz
    spectrumwaterfall: shape=(len(times),len(frequencies))
    """
    #frequencies are hard-coded based on Abrahams notes
    df = .002 #WAG on the orbcomm spectral res
    freqs = np.arange(-3,4)*df + 137.500
    orbTimes = []
    orbData = []
    for ORB_file in infiles:
        lines = open(ORB_file).readlines()
        for line in lines:
            string = line.strip(' \n')
            if len(string.split(' ')) == 25:
                orbTimes.append(float(string.split()[0]))
                orbData.append(map(float,string.strip(' \n').split()[1:]))

    orbData = np.array(orbData)
    orbTimes = Time(orbTimes,format='gps')
    assert(orbData.shape[1]==24)
    chans = getsatfourchanNG_channels[ant+'_'+pol]
    return orbTimes,freqs,dB2(orbData[:,chans])
def channel_select(freqs,rxspectrum,channel):
    """
    input:
        freqs: measured frequences in MHz
        rxspectrum: power in volt^2 shape(len(times),len(freqs))
        channel: give a channel as an int or a float frequency in MHz

    return:
        a single vector ntimes long

    """
    if type(channel)==int:
        if channel>len(freqs):
            print(("error: channel",channel))
            print(("not found in input freqs vector of length",len(freqs)))
            return None
        mychan=channel
    elif type(channel)==float:
        if channel>freqs.max() or channel<freqs.min():
            print(("error: selected freq",channel))
            print(("not found in input freqs vector spanning",freqs.min(),freqs.max()))
            return None
        mychan = np.abs(freqs-channel).argmin()
    return rxspectrum[:,mychan]
def interp_rx(postimes,rxtimes,rx):
    """
    input:
        postimes: astropy.Time.Time vector (output points)
        rxtime: astropy.time.Time vector (input points)
        Assumes that both position and spectrum data have been properly flagged
        and that the flags match between the two

    return:
        interpolation of the rx power to the gps times
    Note: this is just a general interpolation function that uses astropy times
       and can be used for anything

    """
    power_interp_model = interp1d(rxtimes.gps,rx, bounds_error=False)
    rx_interp = power_interp_model(postimes.gps)
    return rx_interp
def flag_apm_pos(postimes,positions,waypoint_times=None):
    """
    input:
        postimes: astropy.time.Time vector
        positions: (3,len(postimes)), lat (deg),lon (deg),relalt (m)
    """
    return np.zeros(len(postimes))
def flag_angles(angletimes,angles,sigma=2):
    """
    input:
        angletimes:astropy.time.Time vector
        angles: (1,len(angletimes))

        sigma: flag values more than this many sigmas above the mean

    return:
        mask
        times during which angles are bad
    """
    #generate a list of bad angletimes

    yawcos = np.cos(angles[0]*np.pi/180)
    mean_yawcos = np.mean(yawcos)
    if mean_yawcos>0.5:
        yawcos = np.sin(angles[0]*np.pi/180) #branch cut issues!
        mean_yawcos = np.mean(yawcos)
    std_yawcos = np.std(yawcos)
    yawmask = np.abs(yawcos-mean_yawcos)/std_yawcos>sigma
    badyaw_indices = np.where(yawmask)[0]
    return yawmask,angletimes[badyaw_indices]
def apply_flagtimes(datatimes,flagtimes,dt):
    #generate a mask for postimes (astropy.time.Time)
    #given a list of times which are bad (astropy.time.Time)
    #flag anything within dt seconds (float seconds)
    mask = np.zeros(len(datatimes))
    for t in flagtimes.gps:
        bad_ind = np.where(np.logical_and(
                        datatimes.gps>(t-dt),
                        datatimes.gps<(t+dt)))
        mask[bad_ind] = 1
    return mask
def flag_waypoints(postimes,waypoint_times):
    """
    input:
        postimes: astropy.time.Time vector matching GPS solutions
        waypoint_times: astropy.time.Time entries matching times reached wypts

    return:
        flags on the postimes time base (ie matching len(postimes))
    """
    return np.zeros(len(postimes))

def mission_endpoint_flagging(pos_data,wpt_data):
    """Read in position and waypoint array, flag all waypoints

    Args:
        ulog (int): the ulog to be converted.

    Returns:
        flagged_array: array of flagged data.
        mission_data: array of valid mission data.

    """
    flagged_indices = []
    mission_indices = []
    mission_start = 0
    mission_end = wpt_data[-1][0]

    for row in wpt_data:
        if row[1] == 1:
            mission_start = row[0]
            break

    for index,row in enumerate(pos_data):
        if row[0]<mission_start or row[0]>mission_end: flagged_indices.append(index)
        else: mission_indices.append(index)

    flagged_data = np.delete(pos_data,mission_indices,0)
    mission_data = np.delete(pos_data,flagged_indices,0)
    return flagged_data, mission_data


def get_data(infile,filetype=None,freqs=[],freq=0.0,freq_chan=None,
             ant=None,dip=None,width=100,times=None,waypts=None,nfft=1024,start_lines=0):#isList=False,

    if filetype == 'gps':
        gps_arr = []
        gps_files = glob.glob(infile)
        for gps_file in gps_files:
            lines = open(gps_file).readlines()
            if not len(lines) == 0:
                for line in lines:
                    if line.startswith('#'):
                        continue
                    line = line.rstrip('\n').split(',')
                    if len(line) == 4: # Make sure line has finished printing
                        gps_arr.append(map(float,line))
        gps_arr = np.array(gps_arr)
        gps_times,lats,lons,alts = np.split(gps_arr,
                                            [1,2,3],
                                            axis=1)
        gps_times = Time(gps_times,format='gps')
        lats = lats.squeeze()
        lons = lons.squeeze()
        alts = alts.squeeze()
        '''
        gps_arr = [map(float,line.rstrip('\n').split(','))\
        for line in lines[2:] if len(line.split(','))==4 and\
        not line.startswith('#')]
        '''
        return gps_times,lats.squeeze(),lons.squeeze(),alts.squeeze()

    elif filetype == 'apm':
        lats,lons,alts = [],[],[]
        weektimes = []
        apm_files = glob.glob(infile)
        for apm_file in apm_files:
            print('Reading in %s...' %apm_file)
            lines = open(apm_file).readlines()
            if not len(lines) == 0:
                for line in lines:
                    if line.startswith('GPS'):
                        lats.append(map(float,line.split(',')[7:8]))
                        lons.append(map(float,line.split(',')[8:9]))
                        alts.append(map(float,line.split(',')[9:10]))
                        weektimes.append(map(float,line.split(',')[3:5])) #ms and week number
        weektimes = np.array(weektimes)
        apm_times = weektimes[:,1]*SEC_PER_WEEK+weektimes[:,0]/1000.
        apm_times = Time(apm_times,format='gps')
        lats = np.array(lats).squeeze()
        lons = np.array(lons).squeeze()
        alts = np.array(alts).squeeze()
        return apm_times,lats,lons,alts

    elif filetype == 'sh':
        spec_times = []
        spec_raw = []
        spec_files = glob.glob(infile)
        for spec_file in spec_files:
            #print 'Reading in %s...' %spec_file
            lines = open(spec_file).readlines()
            if not len(lines) == 0:
                if len(freqs) == 0:
                    freqs = np.array(map(float,lines[1].rstrip('\n').split(',')[1:]))
                    # Get index of freq for gridding
                    freq_chan = np.where(np.abs(freqs-freq).min()==np.abs(freqs-freq))[0]
                    # Filter freqs around freq_chan
                    freqs = freqs[freq_chan-width:freq_chan+width]
                for line in lines[2+start_lines:]:
                    if line.startswith('#'):
                        continue
                    line = line.rstrip('\n').split(',')
                    if len(line) == (nfft+1): # Make sure line has finished printing
                        spec_times.append(float(line[0]))
                        spec_raw.append(map(float,line[freq_chan-width+1:freq_chan+width+1]))
        spec_times = Time(spec_times,format='unix')
        spec_raw = np.array(spec_raw)
        freqs = np.array(freqs).squeeze()
        return spec_times,spec_raw,freqs,freq_chan

    elif filetype == 'echo':
        all_Data = []
        freqs = []
        echo_files = glob.glob(infile)
        for echo_file in echo_files:
            lines = open(echo_file).readlines()
            lat0,lon0 = map(float,lines[2].rstrip('\n').split(':')[1].strip(' ').split(','))
            freqs = map(float,lines[3].rstrip('\n').split(':')[1].strip(' ').split(','))
            #freqs = np.array(freqs)
            for line in lines:
                if line.startswith('#'):
                    continue
                line = line.rstrip('\n').split(',')
                if len(line) == (len(freqs)+5):
                    if not line[1] == '-1':
                        all_Data.append(map(float,line))
        all_Data = np.array(all_Data)
        spec_times,lats,lons,alts,yaws,spec_raw = (all_Data[:,0],all_Data[:,1],\
                                         all_Data[:,2],all_Data[:,3],\
                                         all_Data[:,4],\
                                         all_Data[:,5:])
        spec_times = Time(spec_times,format='gps')
        lats = lats.squeeze(); lats = np.insert(lats,0,lat0)
        lons = lons.squeeze(); lons = np.insert(lons,0,lon0)
        alts = alts.squeeze()
        freqs = np.array(freqs)
        return spec_times,spec_raw,freqs,lats,lons,alts#,lat0,lon0

    elif filetype == 'orbcomm':
        all_Data = []
        lines = open(infile).readlines()
        for line in lines[:]: # Data begins on fifth line of accumulated file
            if line.startswith('#'):
                continue
            elif not line.split(',')[1] == '-1':
                all_Data.append(map(float,line.rstrip('\n').split(',')))
        all_Data = np.array(all_Data)
        spec_times,lats,lons,alts,yaws = (all_Data[:,1],all_Data[:,2],\
                                          all_Data[:,3],all_Data[:,4],\
                                          all_Data[:,5])
        if ant == 'N':
            lat0,lon0 = (38.4248532,-79.8503723)
            if 'NS' in infile:
                spec_raw = all_Data[:,12:17] # N antenna, NS dipole
            if 'EW' in infile:
                spec_raw = all_Data[:,24:29] # N antenna, EW dipole
        elif ant == 'S':
            lat0,lon0 = (38.4239235,-79.8503418)
            if 'NS' in infile:
                spec_raw = all_Data[:,6:11] # S antenna, NS dipole
            if 'EW' in infile:
                spec_raw = all_Data[:,18:23] # S antenna, EW dipole
        spec_times = Time(spec_times,format='gps')
        lats = lats.squeeze()
        lons = lons.squeeze()
        alts = alts.squeeze()
        yaws = yaws.squeeze()
        return spec_times,spec_raw,lats,lons,alts,yaws

    elif filetype == 'start-stop':
        time_ranges = []
        lines = open(infile).readlines()
        for line in lines:
            if line.startswith('#'):
                continue
            line = line.rsrtip('\n').split(' ')
            if not len(line) == 0:
                time_ranges.append(map(float,line[0:2]))
        time_ranges = np.array(time_ranges).squeeze()
        return time_ranges

    elif filetype == 'waypts':
        waypt_times = []
        lines = open(infile).readlines()
        for line in lines:
            if line.startswith('#'):
                continue
            line = line.rstrip('\n')
            waypt_times.append(line)
        waypt_times = np.array(waypt_times).squeeze()
        return waypt_times


    else:
        print('\nNo valid filetype found for %s' %infile)
        print('Exiting...\n\n')
        sys.exit()


def get_start_stop_times(infile):
    # infile can be filename or glob

    start_stop_times = []
    apm_files = glob.glob(infile)
    for apm_file in apm_files:
        lines=open(apm_file).readlines()
        weektimes = []
        for line in lines:
            if line.startswith('GPS'):
                weektimes.append(map(float,line.split(',')[3:5]))
        weektimes = np.array(weektimes)
        seconds = weektimes[:,1]*SEC_PER_WEEK + weektimes[:,0]/1000.
        times = Time(seconds, format='gps')
        mintime = times.gps.min()
        maxtime = times.gps.max()
        start_stop_times.append([mintime,maxtime])
    return start_stop_times


def get_way(infile):
    lines=open(infile).readlines()
    GPS_weektimes,GPS_arm,CMD_time,CMD_num =[],[],[],[]
    for line in lines[630:]:
        if line.startswith('GPS'):
            GPS_weektimes.append(map(float,line.split(',')[3:5]))
            GPS_arm.append(float(line.split(',')[1]))
        if line.startswith('CMD'):
            CMD_time.append(float(line.split(',')[1].strip()))
            CMD_num.append(int(line.split(',')[3].strip()))
    GPS_weektimes = np.array(GPS_weektimes)
    GPS_seconds = GPS_weektimes[:,1]*SEC_PER_WEEK + GPS_weektimes[:,0]/1000.
    GPS_arm= Time((np.array(GPS_arm[0])*APMLOG_SEC_PER_TICK), format = 'gps')
    GPS_time = Time(GPS_seconds, format='gps')
    CMD_time = (np.array(CMD_time).astype(float))*APMLOG_SEC_PER_TICK
    return GPS_time, GPS_arm, np.array(CMD_num), CMD_time


def get_filter_times(infile,first_waypt=3,waypts=False):
    # infile can be filename or glob
    waypoint_times = []
    start_stop_times = []
    apm_files = glob.glob(infile)
    for apm_file in apm_files:
        GPS_times,GPS_arm,CMD_num,CMD_times = get_way(apm_file)
        CMD_times = Time((CMD_times+(GPS_times.gps[0]-GPS_arm.gps)),
                         format='gps')

        for k,CMD in enumerate(CMD_num):
            if CMD==first_waypt:
                start = int(np.round((CMD_times.gps[k]),0))
            if CMD==CMD_num.max():
                stop = int(np.ceil((CMD_times.gps[k])))
                duration =  int(np.ceil((CMD_times.gps[k]))) - start

        start_stop_times.append([start,stop,duration])
        if waypts:
            for i in range(1,CMD_times.shape[0]):
                waypoint_times.append(CMD_times[i].gps)
    print(start_stop_times)
    start_stop_times = np.array(start_stop_times)
    if waypts:
        waypoint_times = np.array(waypoint_times)
        return start_stop_times,waypoint_times
    else:
        return start_stop_times

def read_tlog_txt(tlog):
    """Read in text files converted from tlogs, put them into appropriate arrays.

    Args:
        tlog (int): the text tlog to be read.

    Returns:
        wpt_array: waypoints.
        global_array: global position.
        local_array: local position.
        gps_array: gps raw data.
    """
    wpt_data = []
    global_data = []
    local_data = []
    gps_data = []
    #att_data = []

    lines = open(tlog).readlines()
    for line in lines:

        if line.find('mavlink_mission_item_reached_t') != -1:
            datapoints = line.split()
            if datapoints[11]=='mavlink_mission_item_reached_t': wpt_data.append([datapoints[0]+' '+datapoints[1]+' '+datapoints[2],datapoints[13]])
        elif line.find('mavlink_global_position_int_t') != -1:
            datapoints = line.split()
            if datapoints[15]!='time_boot_ms': global_data.append([datapoints[0]+' '+datapoints[1]+' '+datapoints[2],float(datapoints[13])/1e3,float(datapoints[15])/1e7,float(datapoints[17])/1e7,(float(datapoints[19])/1e3)-1477.8,float(datapoints[29])/1e2])
        elif line.find('mavlink_local_position_ned_t') != -1:
            datapoints = line.split()
            if datapoints[15]!='time_boot_ms': local_data.append([datapoints[0]+' '+datapoints[1]+' '+datapoints[2],float(datapoints[13])/1e3,datapoints[15],datapoints[17],float(datapoints[19])*-1])
        elif line.find('mavlink_gps_raw_int_t') !=- 1:
            datapoints = line.split()
            if datapoints[15]!='time_usec': gps_data.append([datapoints[0]+' '+datapoints[1]+' '+datapoints[2],float(datapoints[13])/1e6,float(datapoints[15])/1e7,float(datapoints[17])/1e7,float(datapoints[19])/1e3])
        #elif line.find('mavlink_attitude_t') != -1:
            #datapoints = line.split()
            #if datapoints[15]!='body_roll_rate' and datapoints[15]!='time_boot_ms': att_data.append([datapoints[1],datapoints[13],datapoints[15],datapoints[17],datapoints[19]])

    wpt_data = DatetimetoUnix(wpt_data)
    global_data = DatetimetoUnix(global_data)
    local_data = DatetimetoUnix(local_data)
    gps_data = DatetimetoUnix(gps_data)
    #DatetimetoUnix(att_data)

    wpt_array = np.array(wpt_data,dtype='int')
    global_array = np.array(global_data,dtype='float')
    local_array = np.array(local_data,dtype='float')
    gps_array = np.array(gps_data,dtype='float')
    #att_array = np.array(att_data)
    return wpt_array, global_array, local_array, gps_array#, att_array

def read_ulog(ulog, output=None, messages='vehicle_global_position,vehicle_local_position,vehicle_gps_position'):
    """Read in ulog file, put them into appropriate arrays, then save to .csv

    Input:
        ulog (int): the ulog to be converted.

    Output:
        global_array: global position.
        local_array: local position.
        gps_array: gps raw data.
    """
    name = ulog[:-4]
    if output:
        pyucsv.convert_ulog2csv(ulog,messages=messages, output=output ,delimiter=',')

        global_data = np.genfromtxt(name+'_vehicle_global_position_0.csv', delimiter=',',skip_header=1,usecols=(0,1,2,3,9))
        global_data[:,0] = global_data[:,0]/1e6
        global_data[:,3] = global_data[:,3]-1477.8

        local_data = np.genfromtxt(name+'_vehicle_local_position_0.csv', delimiter=',',skip_header=1,usecols=(0,1,2,3,4,5,6,20,21))
        local_data[:,0] = local_data[:,0]/1e6
        local_data[:,6] = local_data[:,6]*-1

        gps_data = np.genfromtxt(name+'_vehicle_gps_position_0.csv', delimiter=',',skip_header=1,usecols=(0,1,2,3,4))
        gps_data[:,0] = gps_data[:,0]/1e6
        gps_data[:,1] = gps_data[:,1]/1e6
        gps_data[:,2] = gps_data[:,2]/1e7
        gps_data[:,3] = gps_data[:,3]/1e7
        gps_data[:,4] = gps_data[:,4]/1e3
    else:
        msg_filter = messages.split(',') if messages else None
        log=pyu.ULog(ulog, message_name_filter_list=msg_filter)
        biglist=[]
        for data in log.data_list:
            data_keys = [f.field_name for f in data.field_data]
            data_keys.remove('timestamp')
            data_keys.insert(0, 'timestamp')
            datalist=[]
            for i in range(len(data.data['timestamp'])):
                rowlist=[]
                for k in range(len(data_keys)):
                    rowlist.append(data.data[data_keys[k]][i])
                datalist.append(rowlist)
            biglist.append((str(data.name),np.asarray(datalist, dtype=float)))

        for i,mess in enumerate(msg_filter):
            if "global" in biglist[i][0]:
                global_data = biglist[i][1][:,[0,1,2,3,9]]
            if "local" in biglist[i][0]:
                local_data = biglist[i][1][:,[0,1,2,3,4,5,6,20,21]]
            if "gps" in biglist[i][0]:
                gps_data = biglist[i][1][:,[0,1,2,3,4]]

        global_data[:,0] = global_data[:,0]/1e6
        global_data[:,3] = global_data[:,3]-1477.8

        local_data[:,0] = local_data[:,0]/1e6
        local_data[:,6] = local_data[:,6]*-1

        gps_data[:,0] = gps_data[:,0]/1e6
        gps_data[:,1] = gps_data[:,1]/1e6
        gps_data[:,2] = gps_data[:,2]/1e7
        gps_data[:,3] = gps_data[:,3]/1e7
        gps_data[:,4] = gps_data[:,4]/1e3

        #u_log_dict = {'global_position_u':,'local_position_u':,'gps_position_u':gps_data}
    return global_data, local_data, gps_data

def read_h5(dataFile):
    """
    Read in ulog file, put them into appropriate arrays

    Input:
        target_data (HDF5 data file): the datafile for the received power for the target antenna, saved in in h5 format.

    Output:
        dataDict: A dictionary containing the observation data. Includes observations, tunings, times, XX and YY polarizations, frequencies
    """

    target_data = h5py.File(dataFile,'r')
    keys = [key for key in target_data.keys()]
    #obs_keys = [obsKey for key in keys]
    dataDict = {}
    for key in keys:
        obsKeys = [obsKey for obsKey in target_data[key].keys()]
        obsDict = {}
        for obsKey in obsKeys:
            if obsKey == 'time':
                obsDict[obsKey] = np.asarray(target_data[key][obsKey])
            if obsKey != 'time':
                tuningKeys = [tunKey for tunKey in target_data[key][obsKey].keys()]
                tunDict = {}
                dataKeys = []
                for tunKey in tuningKeys:
                    #print(key, obsKey, tunKey)
                    data = np.asarray(target_data[key][obsKey][tunKey])
                    tunDict[tunKey] = data
                obsDict[obsKey] = tunDict
        dataDict[key] = obsDict
    return dataDict

def CST_to_hp(beamfile,outfile,nside=8,rot=0,zflip=False):
    '''
    Reads in a ASCII formatted CST export file and returns a healpix map.
    Also saves a .fits file to the current directory.
    This function is an adaptation of CST_to_healpix.py in the ECHO github.
    beamfile = CST export file
    outfile = name of the generated fits file, string
    nside = number of sides per healpix pixel, must be 2^n int, 8 is typical
    rot = rotates around the pole by 90deg*rot
    zflip = inverts the Z axis
    '''

    raw_data = np.loadtxt(beamfile,skiprows=2,usecols=(0,1,2))
    thetas = raw_data[:,0]*np.pi/180 #radians
    phis = raw_data[:,1]*np.pi/180 #radians
    gain = raw_data[:,2]
    #account for stupid CST full circle cuts
    phis[thetas<0] += np.pi
    thetas[thetas<0] = np.abs(thetas[thetas<0])

    phis += rot*(np.pi/2)
    if zflip==True: thetas = np.pi - thetas

    hp_indices = hp.ang2pix(nside,thetas,phis)
    hp_map = np.zeros(hp.nside2npix(nside))
    hp_map[hp_indices] = gain
    hp_map -= hp_map.max()
    hp.write_map(outfile,hp_map,fits_IDL=False,overwrite=True)
    return hp_map

def read_CST_puv(CST_txtfile, beam_type, frequency, telescope_name, feed_name, feed_version, model_name, model_version, feed_pol):
    '''
    Reads in a ASCII formatted CST export file and returns a beam model using pyuvbeam.

    CST_txtfile: CST export file
    beam_type (str): efield or power
    frequency (list, Hz): our reference frequency
    telescope_name (str): The instrument name
    feed_name (str): The name of the feed
    feed_version (str): The version of the feed
    model_name (str): Name for the model
    model_version (str): version of the model
    feed_pol (str): polarization of the feed ('x','y','xx','yy')
    '''
    beam = UVBeam()
    beam.read_cst_beam(CST_txtfile, beam_type=beam_type, frequency=frequency,
                   telescope_name=telescope_name, feed_name=feed_name, feed_version=feed_version,
                   model_name = model_name, model_version=model_version, feed_pol=feed_pol)
    return beam
