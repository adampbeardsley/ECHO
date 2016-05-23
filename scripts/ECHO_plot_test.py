'''

    Author: Jacob Burba

    ECHO_plot.py does useful things for some and pointless things for others.  Such is life.
    --lat0 and --lon0 optional

'''


from matplotlib import cm,use
use('TkAgg')
from matplotlib.collections import PolyCollection
from mpl_toolkits.axes_grid1 import make_axes_locatable
from astropy.time import Time

import urllib2,optparse,sys,json,time,warnings
import numpy as np
import healpy as hp
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt


o = optparse.OptionParser()
o.set_description('Queries ground station server for interpolated GPS position')
o.add_option('--acc_file',type=str,help='Accumulated file for plotting')
o.add_option('--nsides',type=int,default=8,help='Number of sides for Healpix plotting (Default = 8)')
o.add_option('--realtime',action='store_true',help='Specify realtime or not')
o.add_option('--lat0',type=float,help='Latitude of antenna under test')
o.add_option('--lon0',type=float,help='Longitude of antenna under test')
o.add_option('--freq',type=float,help='Peak frequency to look for in data')
opts,args = o.parse_args(sys.argv[1:])



def get_data(inFile):
    # Read in preprocessed file
    # The first two lines contain comment and formatting information
    # Third line contains lat0 and lon0
    # Column format is: 0 Time [gps s], 1 lat [deg], 2 lon [deg], 3 alt [m], 4: spectrum (dB)

    all_Data = []
    freqs = []
    #print '\nReading in %s...' %inFile
    lines = open(inFile).readlines()

    # Add information from flight to all_Data array
    if not 'transmitter' in inFile:
        lat0,lon0 = map(float,lines[2].rstrip('\n').split(':')[1].strip(' ').split(','))
        freqs = map(float,lines[3].rstrip('\n').split(':')[1].strip(' ').split(','))
        freqs = np.array(freqs)
    for line in lines[4:]: # Data begins on fifth line of accumulated file
        if line.startswith('#'):
            continue
        elif not line.split(',')[1] == '-1':
                all_Data.append(map(float,line.rstrip('\n').split(',')))

    all_Data = np.array(all_Data)
    #print 'Converted to array with shape %s and type %s' %(all_Data.shape,all_Data.dtype)

    # Extract information from all_Data array
    if 'transmitter' in inFile: # Green Bank data
        spec_times,lats,lons,alts = (all_Data[:,1],all_Data[:,2],all_Data[:,3],all_Data[:,4])
        if 'Nant' in inFile:
            lat0,lon0 = (38.4248532,-79.8503723)
            if 'NS' in inFile:
                spec_raw = all_Data[:,12:17] # N antenna, NS dipole
            if 'EW' in inFile:
                spec_raw = all_Data[:,24:29] # N antenna, EW dipole
        if 'Sant' in inFile:
            lat0,lon0 = (38.4239235,-79.8503418)
            if 'NS' in inFile:
                spec_raw = all_Data[:,6:11] # S antenna, NS dipole
            if 'EW' in inFile:
                spec_raw = all_Data[:,18:23] # S antenna, EW dipole
    else:
        spec_times,lats,lons,alts,spec_raw = (all_Data[:,0],all_Data[:,1],all_Data[:,2],\
                                                                    all_Data[:,3],all_Data[:,4:])
    return all_Data,spec_times,spec_raw,freqs,lats,lons,alts,lat0,lon0
# end get_data


def griddata(x, y, z, binsize=0.01, retbin=True, retloc=True, retrms=True):
    # Get extrema values.
    xmin, xmax = x.min(), x.max()
    ymin, ymax = y.min(), y.max()
    # Make coordinate arrays.
    xi = np.arange(xmin, xmax+binsize, binsize)
    yi = np.arange(ymin, ymax+binsize, binsize)
    xi, yi = np.meshgrid(xi,yi)

    # Make the grid.
    grid = np.zeros(xi.shape, dtype=x.dtype)
    nrow, ncol = grid.shape
    if retbin: bins = np.copy(grid)
    if retrms: rmsBins = np.copy(grid)

    # Make arrays to store counts/rms for Healpix data
    gcounts = np.zeros_like(z)
    grms = np.zeros_like(z)

    # Create list in same shape as grid to store indices
    if retloc:
        wherebin = np.copy(grid)
        wherebin = wherebin.tolist()
    # Fill in the grid.
    for row in range(nrow):
        for col in range(ncol):
            xc = xi[row, col]    # x coordinate.
            yc = yi[row, col]    # y coordinate.

            # Find the position that xc and yc correspond to.
            posx = np.abs(x - xc)
            posy = np.abs(y - yc)
            ibin = np.logical_and(posx < binsize/2., posy < binsize/2.)
            ind  = np.where(ibin == True)[0]

            # Fill the bin.
            bin = z[ibin]
            gcounts[ibin] = np.sum(ibin) # Update counts at each x position
            if retloc: wherebin[row][col] = ind
            if retbin: bins[row, col] = bin.size
            if bin.size != 0:
                binval = np.median(bin)
                grid[row, col] = binval
                if retrms:
                    rmsBins[row,col] = np.std(bin)
                    grms[ibin] = np.std(bin)
            else:
                grid[row, col] = np.nan   # Fill empty bins with nans.
                if retrms:
                    rmsBins[row,col] = np.nan
                    grms[ibin] = np.nan

    # Return the grid
    if retbin:
        if retloc:
            if retrms:
                return np.ma.masked_invalid(grid), bins, np.ma.masked_invalid(rmsBins), wherebin, xi, yi, gcounts, grms
            else:
                return np.ma.masked_invalid(grid), bins, wherebin, xi, yi, gcounts, grms
        else:
            return np.ma.masked_invalid(grid), bins, xi, yi, gcounts, grms
    else:
        if retloc:
            if retrms:
                return np.ma.masked_invalid(grid), np.ma.masked_invalid(rmsBins), wherebin, xi, yi, gcounts, grms
            else:
                return np.ma.masked_invalid(grid), wherebin, xi, yi, gcounts, grms
        else:
            if retrms:
                return np.ma.masked_invalid(grid), np.ma.masked_invalid(rmsBins), xi, yi, gcounts, grms
            else:
                return np.ma.masked_invalid(grid), xi, yi, gcounts, grms
# end griddata


def make_beam(lats,lons,alts,spec_raw,lat0,lon0,volts=False):
    # Convert lat/lon to x/y
    if opts.lat0 and opts.lon0:
        x,y = latlon2xy(lats,lons,opts.lat0,opts.lon0)
    else:
        x,y = latlon2xy(lats,lons,lat0,lon0)
    # Obtain spherical coordinates for x, y, and alt
    rs,thetas,phis = to_spherical(x,y,alts)

    # z (power) will set color value for gridded data
    #freqIndex = np.argmax(spec_raw[0,:])
    freqIndex = 10
    # Only extract information from appropriate column (index = 10)
    z = spec_raw[:,freqIndex]
    if volts:
        # Distance normalization
        r0 = 100 # reference position for distance normalization (unit: meters)
        z = 10*np.log10((2*z**2)*(rs/r0)**2)
        # log(V^2) -> dB
    # Normalize for plotting [-inf,0]
    z -= z.max()

    # Set binsize (used in function griddata)
    # Affects the apparent size of the pixels on the plot created below.
    binsize=5
    # Obtain gridded data
    grid,bins,rmsBins,binloc,xg,yg,gcounts,grms = griddata(x,y,z,binsize=binsize)

    # Healpix things
    nsides = opts.nsides
    nPixels = hp.nside2npix(nsides)
    hpx_beam = np.zeros(nPixels)
    hpx_counts = np.zeros(nPixels)
    hpx_rms = np.zeros(nPixels)
    # Find pixel # for a given theta and phi
    pixInd = hp.ang2pix(nsides,thetas,phis,nest=False)
    # Set pixel values at pixInd to power values
    hpx_beam[pixInd] = z
    hpx_counts[pixInd] = gcounts
    hpx_rms[pixInd] = grms
    # Grey out pixels with no measurements
    hpx_beam[hpx_beam == 0] = np.nan
    hpx_counts[hpx_counts == 0] = np.nan
    hpx_rms[hpx_rms == 0] = np.nan

    return hpx_beam,hpx_counts,hpx_rms
# end make_beam


def latlon2xy(lat,lon,lat0,lon0):
    x = r_earth*(lon - lon0)*(np.pi/180)
    y = r_earth*(lat - lat0)*(np.pi/180)
    return x,y
# end latlon2xy


def to_spherical(x,y,z):
    # x and y are cartesian coordinates
    # z is relative altitude
    rhos = np.sqrt(x**2+y**2+z**2)
    thetas = np.arccos(z/rhos) # Zentih angle
    phis = np.arctan2(y,x) # Azimuthal angle
    return rhos,thetas,phis
# end to_spherical


# Declare constants
i = 0
r_earth = 6371000 # meters



def animate_beam(beam_plot,hpx_beam):
    pix = np.argwhere(np.isnan(hpx_beam)==False).squeeze()
    boundaries = hp.boundaries(opts.nsides,pix)
    verts = np.swapaxes(boundaries[:,0:2,:],1,2)
    coll = PolyCollection(verts, array=hpx_beam[np.isnan(hpx_beam)==False],\
                                    cmap=cm.gnuplot,edgecolors='none')
    beam_plot.collections.remove(beam_plot.collections[-1])
    beam_plot.add_collection(coll)
# end animate_beam


def adjustErrbarxy(errobj, x, y, y_error):
    # http://stackoverflow.com/questions/25210723/matplotlib-set-data-for-errorbar-plot
    ln, (erry_top, erry_bot), barsy = errobj
    x_base = x
    y_base = y
    ln.set_ydata(y)
    yerr_top = y_base + y_error
    yerr_bot = y_base - y_error
    erry_top.set_ydata(yerr_top)
    erry_bot.set_ydata(yerr_bot)
    new_segments_y = [np.array([[x, yt], [x,yb]]) for x, yt, yb in zip(x_base, yerr_top, yerr_bot)]
    barsy[0].set_segments(new_segments_y)
# end adjustErrbarxy

def animate_cuts(cuts_E_line,cuts_H_line,hpx_beam,ell,az):
    beam_slice_E = hp.pixelfunc.get_interp_val(hpx_beam,ell,az)
    beam_slice_E_err = hp.pixelfunc.get_interp_val(hpx_rms,ell,az)
    beam_slice_H = hp.pixelfunc.get_interp_val(hpx_beam,ell,az+np.pi/2)
    beam_slice_H_err = hp.pixelfunc.get_interp_val(hpx_rms,ell,az+np.pi/2)

    adjustErrbarxy(cuts_E_line,ell,beam_slice_E,beam_slice_E_err)
    adjustErrbarxy(cuts_H_line,ell,beam_slice_H,beam_slice_H_err)
# end animate_cuts


fmin,fmax = int(opts.freq)-1,int(opts.freq)+1 # MHz; for plotting
time_range = 200 # Time range in seconds of peak plot window
rmswindow = 10

# Get initial data from Signal Hound
all_Data,spec_times,spec_raw,freqs,lats,lons,alts,lat0,lon0 = get_data(opts.acc_file)
#print freqs.shape,spec_raw.shape
if spec_times.shape[0] == 0: # Ensure data in inFile
    print 'Invalid data: array with zero dimension\nExiting...\n'
    sys.exit()

# Initialize plotting figure
fig = plt.figure(figsize=(13,9),dpi=80,facecolor='w',edgecolor='w') # figsize=(16,9))
mng = plt.get_current_fig_manager() # Make figure full screen
# Make background subplot for title for all plots
ax = fig.add_subplot(111)
ax.set_title(r'Real-time ECHO Data',y=1.08,size=16)
ax.spines['top'].set_color('none')
ax.spines['bottom'].set_color('none')
ax.spines['left'].set_color('none')
ax.spines['right'].set_color('none')
ax.tick_params(labelcolor='w', top='off', bottom='off', left='off', right='off')

# Spectrum plot initialization
gs1 = gridspec.GridSpec(3, 1) # Sets up grid for placing plots


# Make beam, counts, and rms from gridded data
# griddata(...) called in make_beam(...)
hpx_beam,hpx_counts,hpx_rms = make_beam(lats,lons,alts,spec_raw,lat0,lon0)

# Cuts and beam plot initializations
gs2 = gridspec.GridSpec(2, 1,height_ratios=[1,1])
plot_lim = [-40,5]

# Beam plot initialization
#gs = gridspec.GridSpec(1, 2) # Sets up grid for placing plots
#beam_plot = fig.add_subplot(gs[0],aspect='equal')
beam_plot = fig.add_subplot(gs2[0],aspect='equal')
init_beam = 10*np.ones_like(hpx_beam)
init_pix = np.argwhere(init_beam).squeeze()
init_boundaries = hp.boundaries(opts.nsides,init_pix)
init_verts = np.swapaxes(init_boundaries[:,0:2,:],1,2)
init_coll = PolyCollection(init_verts, array=init_beam,\
                                cmap=cm.gnuplot,edgecolors='none')
init_coll.set_clim(plot_lim)
init_coll.cmap.set_over('0.75')

pix = np.argwhere(np.isnan(hpx_beam)==False).squeeze()
boundaries = hp.boundaries(opts.nsides,pix)
verts = np.swapaxes(boundaries[:,0:2,:],1,2)
coll = PolyCollection(verts, array=hpx_beam[np.isnan(hpx_beam)==False],\
                                cmap=cm.gnuplot,edgecolors='none')
coll.set_clim(plot_lim)
beam_plot.add_collection(init_coll) # Ensure pixels can be filled

# Position colorbar next to plot with same height as plot
divider = make_axes_locatable(beam_plot)
cax = divider.append_axes("right", size="5%", pad=0.05)
fig.colorbar(init_coll, cax=cax, use_gridspec=True, label='dB')

beam_plot.add_collection(coll)
beam_plot.autoscale_view()
for radius_deg in [20,40,60,80]:
    r = np.sin(radius_deg*np.pi/180.)
    x = np.linspace(-r,r,100)
    beam_plot.plot(x,np.sqrt(r**2-x**2),'w-',linewidth=3)
    beam_plot.plot(x,-np.sqrt(r**2-x**2),'w-',linewidth=3)

# Cuts plot initialization
#cuts_plot = fig.add_subplot(gs[1])
cuts_plot = fig.add_subplot(gs2[1])

#receiver coordinates
ell = np.linspace(-np.pi/2,np.pi/2)
az = np.zeros_like(ell)
xticks = [-90,-60,-40,-20,0,20,40,60,90]
beam_slice_E = hp.pixelfunc.get_interp_val(hpx_beam,ell,az)
beam_slice_E_err = hp.pixelfunc.get_interp_val(hpx_rms,ell,az)
beam_slice_H = hp.pixelfunc.get_interp_val(hpx_beam,ell,az+np.pi/2)
beam_slice_H_err = hp.pixelfunc.get_interp_val(hpx_rms,ell,az+np.pi/2)

cuts_E_line = cuts_plot.errorbar(ell*180/np.pi,beam_slice_E,\
                                                beam_slice_E_err,fmt='b.',label='ECHO [E]')
cuts_H_line = cuts_plot.errorbar(ell*180/np.pi,beam_slice_H,\
                                                beam_slice_H_err,fmt='r.',label='ECHO [H]')
cuts_plot.legend(loc='lower center')
cuts_plot.set_ylabel('dB')
cuts_plot.set_xlabel('Elevation Angle [deg]')
cuts_plot.set_xlim([-95,95])
cuts_plot.set_xticks(xticks)
cuts_plot.set_ylim(plot_lim)


with warnings.catch_warnings():
    # This raises warnings since tight layout cannot
    # handle gridspec automatically. We are going to
    # do that manually so we can filter the warning.
    warnings.simplefilter("ignore", UserWarning)
    gs2.tight_layout(fig, rect=[0.5, None, None, None])


mng.window.state('zoomed')
plt.show(block=False)
plt.draw()

try:
    while True:
        # Get updated data from Signal Hound
        all_Data,spec_times,spec_raw,freqs,lats,lons,alts,lat0,lon0 = get_data(opts.acc_file)
        hpx_beam,hpx_counts,hpx_rms = make_beam(lats,lons,alts,spec_raw,lat0,lon0)

        # Update plotting window
        if spec_times.shape[0]%10 ==0:
            animate_beam(beam_plot,hpx_beam)
            animate_cuts(cuts_E_line,cuts_H_line,hpx_beam,ell,az)
            plt.draw()
        i += 1


except KeyboardInterrupt:
    print '\nExiting...\n'
    sys.exit()
