import hddm
import pandas as pd
import numpy as np
#import re
import argparse
import sys
import pickle
from statsmodels.distributions.empirical_distribution import ECDF
from scipy.stats import truncnorm
import matplotlib


sys.path.append('simulators')

from cddm_data_simulation import ddm 
from cddm_data_simulation import ddm_flexbound
from cddm_data_simulation import levy_flexbound
from cddm_data_simulation import ornstein_uhlenbeck
from cddm_data_simulation import full_ddm
from cddm_data_simulation import ddm_sdv
from cddm_data_simulation import ddm_flexbound_pre
import cddm_data_simulation as cds

import boundary_functions as bf

# plotting 
import matplotlib.pyplot as plt
import seaborn as sns

# Config -----
config = {'ddm': {'params':['v', 'a', 'z', 't'],
                  'param_bounds': [[-2, 0.5, 0.3, 0.2], [2, 2, 0.7, 1.8]],
                 },
          'angle':{'params': ['v', 'a', 'z', 't', 'theta'],
                   'param_bounds': [[-2, 0.5, 0.3, 0.2, 0.2], [2, 1.8, 0.7, 1.8, np.pi / 2 - 0.5]],
                  },
          'weibull_cdf':{'params': ['v', 'a', 'z', 't', 'alpha', 'beta'],
                         'param_bounds': [[-2, 0.5, 0.3, 0.2, 1.0, 1.0], [2, 1.7, 0.7, 1.8, 4.0, 6.0]]
                        },
          'weibull_cdf_concave':{'params': ['v', 'a', 'z', 't', 'alpha', 'beta'],
                                 'param_bounds': [[-2, 0.5, 0.3, 0.2, 1.5, 1.0], [2, 1.7, 0.7, 1.8, 4.0, 6.0]]
                                 },
          'levy':{'params':['v', 'a', 'z', 'alpha', 't'],
                  'param_bounds':[[-2, 0.4, 0.3, 1.1, 0.1], [2, 1.7, 0.7, 1.9, 1.9]]
                 },
          'full_ddm':{'params':['v', 'a', 'z', 't', 'dw', 'sv', 'dndt'],
                      'param_bounds':[[-2, 0.5, 0.35, 0.3, 0.05, 0.0, 0.05], [2, 2.2, 0.65, 0.3, 0.25, 1.7, 0.2]]
                     },
          
          'ornstein':{'params':['v', 'a', 'z', 'g', 't'],
                      'param_bounds':[[-1.9, 0.4, 0.25, -0.9, 0.1], [1.9, 1.9, 0.75, 0.9, 1.9]]
                     },
          'ddm_sdv':{'params':['v', 'a', 'z', 't', 'sv'],
                     'param_bounds':[[-2.2, 0.5, 0.25, 0.1, 0.3],[ 2.2, 2.2, 0.75, 1.9, 2.2]],
                    },
         }

# DATA SIMULATION ------------------------------------------------------------------------------
def str_to_num(string = '', n_digits = 3):
    new_str = ''
    leading = 1
    for digit in range(n_digits):
        if string[digit] == '0' and leading and (digit < n_digits - 1):
            pass
        else:
            new_str += string[digit]
            leading = 0
    return int(new_str)

def num_to_str(num = 0, n_digits = 3):
    new_str = ''
    for i in range(n_digits - 1, -1, -1):
        if num < np.power(10, i):
            new_str += '0'
    if num != 0:
        new_str += str(num)
    return new_str

def bin_simulator_output(out = [0, 0],
                         bin_dt = 0.04,
                         nbins = 0): # ['v', 'a', 'w', 'ndt', 'angle']
        
    # Generate bins
    if nbins == 0:
        nbins = int(out[2]['max_t'] / bin_dt)
        bins = np.zeros(nbins + 1)
        bins[:nbins] = np.linspace(0, out[2]['max_t'], nbins)
        bins[nbins] = np.inf
    else:  
        bins = np.zeros(nbins + 1)
        bins[:nbins] = np.linspace(0, out[2]['max_t'], nbins)
        bins[nbins] = np.inf

    cnt = 0
    counts = np.zeros( (nbins, len(out[2]['possible_choices']) ) )

    for choice in out[2]['possible_choices']:
        counts[:, cnt] = np.histogram(out[0][out[1] == choice], bins = bins)[0] / out[2]['n_samples']
        cnt += 1
    return counts

def make_parameter_sets(model = 'weibull_cdf',
                        param_dict = None,
                        n_parameter_sets = 10):
    
    parameter_data = np.zeros((n_parameter_sets, len(config[model]['params'])))
    
    if param_dict is not None:
        cnt = 0
        for param in config[model]['params']:

            if param in param_dict.keys():

                if (len(param_dict[param]) == n_parameter_sets) or (len(param_dict[param]) == 1):
                    # Check if parameters are properly in bounds
                    if np.sum(np.array(param_dict[param]) < config[model]['param_bounds'][0][cnt]) > 0 \
                    or np.sum(np.array(param_dict[param]) > config[model]['param_bounds'][1][cnt]) > 0:
                        
                        print('The parameter: ', 
                              param, 
                              ', is out of the accepted bounds [', 
                              config[model]['param_bounds'][0][cnt], 
                              ',', 
                              config[model]['param_bounds'][1][cnt], ']')
                        return 
                    else:
                        parameter_data[:, cnt] = param_dict[param]
                else:
                    print('Param dict not specified correctly. Lengths of parameter lists needs to be 1 or equal to n_param_sets')

            else:
                parameter_data[:, cnt] = np.random.uniform(low = config[model]['param_bounds'][0][cnt],
                                                           high = config[model]['param_bounds'][1][cnt], 
                                                           size = n_parameter_sets)
            cnt += 1
    else:
        parameter_data = np.random.uniform(low = config[model]['param_bounds'][0],
                                           high = config[model]['param_bounds'][1],
                                           size = (n_parameter_sets, len(config[model]['params'])))
                                           
    return pd.DataFrame(parameter_data, columns = config[model]['params'])

def simulator(theta, 
              model = 'angle', 
              n_samples = 1000,
              bin_dim = None):
    
    # Useful for sbi
    if type(theta) == list or type(theta) == np.ndarray:
        pass
    else:
        theta = theta.numpy()
    
    if model == 'ddm':
        x = ddm_flexbound(v = theta[0], 
                          a = theta[1], 
                          w = theta[2], 
                          ndt = theta[3], 
                          n_samples = n_samples,
                          boundary_multiplicative = True,
                          boundary_params = {},
                          boundary_fun = bf.constant)
                                             
    
    if model == 'angle':
        x = ddm_flexbound(v = theta[0],
                          a = theta[1], 
                          w = theta[2], 
                          ndt = theta[3], 
                          boundary_fun = bf.angle, 
                          boundary_multiplicative = False,
                          boundary_params = {'theta': theta[4]}, 
                          n_samples = n_samples)
    
    if model == 'weibull_cdf' or model == 'weibull_cdf_concave' or model == 'weibull_cdf2':
        x = ddm_flexbound(v = theta[0], 
                          a = theta[1], 
                          w = theta[2], 
                          ndt = theta[3], 
                          boundary_fun = bf.weibull_cdf, 
                          boundary_multiplicative = True, 
                          boundary_params = {'alpha': theta[4], 'beta': theta[5]}, 
                          n_samples = n_samples)
    
    if model == 'levy':
        x = levy_flexbound(v = theta[0], 
                           a = theta[1], 
                           w = theta[2], 
                           alpha_diff = theta[3], 
                           ndt = theta[4], 
                           boundary_fun = bf.constant, 
                           boundary_multiplicative = True, 
                           boundary_params = {}, 
                           n_samples = n_samples)
    
    if model == 'full_ddm':
        x = full_ddm(v = theta[0],
                     a = theta[1], 
                     w = theta[2], 
                     ndt = theta[3],
                     dw = theta[4], 
                     sdv = theta[5],
                     dndt = theta[6], 
                     boundary_fun = bf.constant, 
                     boundary_multiplicative = True, 
                     boundary_params = {}, 
                     n_samples = n_samples)

    if model == 'ddm_sdv':
        x = ddm_sdv(v = theta[0], 
                    a = theta[1], 
                    w = theta[2], 
                    ndt = theta[3],
                    sdv = theta[4],
                    boundary_fun = bf.constant,
                    boundary_multiplicative = True, 
                    boundary_params = {},
                    n_samples = n_samples)
        
    if model == 'ornstein':
        x = ornstein_uhlenbeck(v = theta[0], 
                               a = theta[1], 
                               w = theta[2], 
                               g = theta[3], 
                               ndt = theta[4],
                               boundary_fun = bf.constant,
                               boundary_multiplicative = True,
                               boundary_params = {},
                               n_samples = n_samples)

    if model == 'pre':
        x = ddm_flexbound_pre(v = theta[0], 
                              a = theta[1], 
                              w = theta[2], 
                              ndt = theta[3],
                              boundary_fun = bf.angle,
                              boundary_multiplicative = False,
                              boundary_params = {'theta': theta[4]},
                              n_samples = n_samples)
    if bin_dim == None:
        return x
    else:
        return bin_simulator_output(x, nbins = bin_dim).flatten()
    
def simulator_condition_effects(n_conditions = 4, 
                                n_samples_by_condition = 1000,
                                condition_effect_on_param = [0], 
                                model = 'angle',
                                ):
     
    param_base = np.tile(np.random.uniform(low = config[model]['param_bounds'][0],
                                           high = config[model]['param_bounds'][1], 
                                           size = (1, len(config[model]['params']))),
                                           (n_conditions, 1))
                         
    #len(config[model]['params']                   
    #print(param_base)
    gt = {}
    for i in range(n_conditions):
        for c_eff in condition_effect_on_param:
            id_tmp = config[model]['params'].index(c_eff)
            #print(id_tmp)
            #print(config[model]['param_bounds'][0])
            param_base[i, id_tmp] = np.random.uniform(low = config[model]['param_bounds'][0][id_tmp], 
                                                      high = config[model]['param_bounds'][1][id_tmp])
            gt[c_eff + '(' + str(i) + ')'] = param_base[i, id_tmp]
    
    for param in config[model]['params']:
        if param in condition_effect_on_param:
            pass
        else:
            id_tmp = config[model]['params'].index(param)
            gt[param] = param_base[0, id_tmp]
            
    #print(param_base)
    dataframes = []
    for i in range(n_conditions):
        sim_out = simulator(param_base[i, :], 
                            model = model, 
                            n_samples = n_samples_by_condition,
                            bin_dim = None)
        
        dataframes.append(hddm_preprocess(simulator_data = sim_out, subj_id = i))
    
    data_out = pd.concat(dataframes)
    data_out = data_out.rename(columns = {'subj_idx': "condition"})
    # print(param_base.shape)
    return (data_out, gt, param_base)

def simulator_hierarchical(n_subjects = 5,
                           n_samples_by_subject = 10,
                           model = 'angle'):

    param_ranges_half = (np.array(config[model]['param_bounds'][1]) - np.array(config[model]['param_bounds'][0])) / 2
    
    global_stds = np.random.uniform(low = 0.01, 
                                    high = param_ranges_half / 6,
                                    size = (1, len(config[model]['param_bounds'][0])))
    
    global_means = np.random.uniform(low = config[model]['param_bounds'][0],
                                     high = config[model]['param_bounds'][1],
                                     size = (1, len(config[model]['param_bounds'][0])))
                                    
    
    dataframes = []
    subject_parameters = np.zeros((n_subjects, 
                                   len(config[model]['param_bounds'][0])))
    gt = {}
    
    for param in config[model]['params']:
        id_tmp = config[model]['params'].index(param)
        gt[param] = global_means[0, id_tmp]
        gt[param + '_std'] = global_stds[0, id_tmp]
    
    for i in range(n_subjects):
        subj_id = num_to_str(i)
        # Get subject parameters
        a = (config[model]['param_bounds'][0] - global_means[0, :]) / global_stds[0, :]
        b = (config[model]['param_bounds'][1] - global_means[0, :]) / global_stds[0, :]
        
        subject_parameters[i, :] = np.float32(global_means[0, :] + (truncnorm.rvs(a, b, size = global_stds.shape[1]) * global_stds[0, :]))
        
        sim_out = simulator(subject_parameters[i, :],
                            model = model,
                            n_samples = n_samples_by_subject,
                            bin_dim = None)
        
        dataframes.append(hddm_preprocess(simulator_data = sim_out, 
                                          subj_id = subj_id))
        
        for param in config[model]['params']:
            id_tmp = config[model]['params'].index(param)
            gt[param + '_subj.' + subj_id] = subject_parameters[i, id_tmp]
        
    data_out = pd.concat(dataframes)
    
    return (data_out, gt, subject_parameters)                 
                         
def hddm_preprocess(simulator_data = None, subj_id = 'none'):
    
    df = pd.DataFrame(simulator_data[0].astype(np.double), columns = ['rt'])
    df['response'] = simulator_data[1].astype(int)
    df['nn_response'] = df['response']
    df.loc[df['response'] == -1.0, 'response'] = 0.0
    df['subj_idx'] = subj_id
    return df

def _make_trace_plotready_single_subject(hddm_trace = None, model = ''):
    
    posterior_samples = np.zeros(hddm_trace.shape)
    
    cnt = 0
    for param in config[model]['params']:
        if param == 'z':
            posterior_samples[:, cnt] = 1 / (1 + np.exp( - hddm_trace['z_trans']))
        else:
            posterior_samples[:, cnt] = hddm_trace[param]
        cnt += 1
    
    return posterior_samples

def _make_trace_plotready_hierarchical(hddm_trace = None, model = ''):
    
    subj_l = []
    for key in hddm_trace.keys():
        if '_subj' in key:
            subj_l.append(str_to_num(key[-3:]))
            #subj_l.append(int(float(key[-3:])))

    dat = np.zeros((max((subj_l)) + 1, hddm_trace.shape[0], len(config[model]['params'])))
    for key in hddm_trace.keys():
        if '_subj' in key:
            id_tmp = str_to_num(key[-3:]) #int(float(key[-3:]))
            if '_trans' in key:
                val_tmp = 1 / ( 1 + np.exp(- hddm_trace[key]))
            else:
                val_tmp = hddm_trace[key]
            dat[id_tmp, : , config[model]['params'].index(key[:key.find('_')])] = val_tmp   
            
    return dat

def _make_trace_plotready_condition(hddm_trace = None, model = ''):
    
    cond_l = []
    for key in hddm_trace.keys():
        if '(' in key:
            cond_l.append(int(float(key[-2])))
    
    dat = np.zeros((max(cond_l) + 1, hddm_trace.shape[0], len(config[model]['params'])))
                   
    for key in hddm_trace.keys():
        if '(' in key:
            id_tmp = int(float(key[-2]))
            if '_trans' in key:
                val_tmp = 1 / ( 1 + np.exp(- hddm_trace[key]))
                dat[id_tmp, : , config[model]['params'].index(key[:key.find('_trans')])] = val_tmp
            else:
                val_tmp = hddm_trace[key]
                dat[id_tmp, : , config[model]['params'].index(key[:key.find('(')])] = val_tmp   
        else:
            if '_trans' in key:
                val_tmp = 1 / ( 1 + np.exp(- hddm_trace[key]))
                key = key[:key.find('_trans')]
            else:
                val_tmp = hddm_trace[key]
                   
            dat[:, :, config[model]['params'].index(key)] = val_tmp
            
    return dat
# --------------------------------------------------------------------------------------------

# Plot bound
# Mean posterior predictives
def model_plot(posterior_samples = None,
               ground_truths_parameters = [],
               ground_truths_data = [],
               cols = 3,
               model_gt = 'weibull_cdf',
               model_fitted = 'angle',
               n_post_params = 500,
               n_plots = 4,
               samples_by_param = 10,
               max_t = 5,
               input_hddm_trace = False,
               datatype = 'single_subject', # 'hierarchical', 'single_subject', 'condition'
               show_model = True,
               ylimit = 2,
               posterior_linewidth = 3,
               gt_linewidth = 3,
               hist_linewidth = 3,
               bin_size = 0.025,
               save = False):
    
    if save == True:
        matplotlib.rcParams['text.usetex'] = True
        #matplotlib.rcParams['pdf.fonttype'] = 42
        matplotlib.rcParams['svg.fonttype'] = 'none'

    # Inputs are hddm_traces --> make plot ready
    if input_hddm_trace and posterior_samples is not None:
        if datatype == 'hierarchical':
            posterior_samples = _make_trace_plotready_hierarchical(posterior_samples, 
                                                                   model = model_fitted)
            print(posterior_samples.shape)
            n_plots = posterior_samples.shape[0]
#             print(posterior_samples)
            
        if datatype == 'single_subject':
            posterior_samples = _make_trace_plotready_single_subject(posterior_samples, 
                                                                     model = model_fitted)
        if datatype == 'condition':
            posterior_samples = _make_trace_plotready_condition(posterior_samples, 
                                                                model = model_fitted)
            n_plots = posterior_samples.shape[0]
            #print(posterior_samples)
            #n_plots = posterior_samples.shape[0]

    if posterior_samples is None and model_gt is None:
        return 'Please provide either posterior samples, \n or a ground truth model and parameter set to plot something here. \n Currently you are requesting an empty plot' 
    
    
    # Taking care of special case with 1 plot
    if n_plots == 1:
        if model_gt is not None:
            ground_truths_parameters = np.expand_dims(ground_truths_parameters, 0)
        if posterior_samples is not None:
            posterior_samples = np.expand_dims(posterior_samples, 0)
        if ground_truths_data is not None:
            ground_truths_data = np.expand_dims(ground_truths_data, 0)
            
    plot_titles = {'ddm': 'DDM', 
                   'angle': 'ANGLE',
                   'full_ddm': 'FULL DDM',
                   'weibull_cdf': 'WEIBULL',
                   'weibull_cdf_concave': 'WEIBULL',
                   'levy': 'LEVY',
                   'ornstein': 'ORNSTEIN UHLENBECK',
                   'ddm_sdv': 'DDM RANDOM SLOPE',
                  }
    
    title = 'Model Plot: '
    
    if model_gt is not None:
        ax_titles = config[model_gt]['params']
    else: 
        ax_titles = ''

    rows = int(np.ceil(n_plots / cols))

    sns.set(style = "white", 
            palette = "muted", 
            color_codes = True,
            font_scale = 2)

    fig, ax = plt.subplots(rows, cols, 
                           figsize = (20, 20), 
                           sharex = False, 
                           sharey = False)
    
    if model_gt is not None:  
        my_suptitle = fig.suptitle(title + plot_titles[model_gt], fontsize = 40)
    else:
        my_suptitle = fig.suptitle(title.replace(':', ''), fontsize = 40)
        
    sns.despine(right = True)
    
    t_s = np.arange(0, max_t, 0.01)
    nbins = int((max_t) / bin_size)

    for i in range(n_plots):
        row_tmp = int(np.floor(i / cols))
        col_tmp = i - (cols * row_tmp)
        
        if rows > 1 and cols > 1:
            ax[row_tmp, col_tmp].set_xlim(0, max_t)
            ax[row_tmp, col_tmp].set_ylim(- ylimit, ylimit)
        elif (rows == 1 and cols > 1) or (rows > 1 and cols == 1):
            ax[i].set_xlim(0, max_t)
            ax[i].set_ylim(-ylimit, ylimit)
        else:
            ax.set_xlim(0, max_t)
            ax.set_ylim(-ylimit, ylimit)
        
        # Run simulations and add histograms
        # True params
        if model_gt is not None:
            out = simulator(theta = ground_truths_parameters[i, :],
                            model = model_gt, 
                            n_samples = 20000,
                            bin_dim = None)
             
            tmp_true = np.concatenate([out[0], out[1]], axis = 1)
            choice_p_up_true = np.sum(tmp_true[:, 1] == 1) / tmp_true.shape[0]
        
        if posterior_samples is not None:
            # Run Model simulations for posterior samples
            tmp_post = np.zeros((n_post_params * samples_by_param, 2))
            idx = np.random.choice(posterior_samples.shape[1], size = n_post_params, replace = False)

            for j in range(n_post_params):
                out = simulator(theta = posterior_samples[i, idx[j], :],
                                model = model_fitted,
                                n_samples = samples_by_param,
                                bin_dim = None)
                                
                tmp_post[(samples_by_param * j):(samples_by_param * (j + 1)), :] = np.concatenate([out[0], out[1]], axis = 1)
        
         #ax.set_ylim(-4, 2)
        if rows > 1 and cols > 1:
            ax_tmp = ax[row_tmp, col_tmp].twinx()
        elif (rows == 1 and cols > 1) or (rows > 1 and cols == 1):
            ax_tmp = ax[i].twinx()
        else:
            ax_tmp = ax.twinx()
        
        ax_tmp.set_ylim(-ylimit, ylimit)
        ax_tmp.set_yticks([])
        
        if posterior_samples is not None:
            choice_p_up_post = np.sum(tmp_post[:, 1] == 1) / tmp_post.shape[0]

#             counts, bins = np.histogram(tmp_post[tmp_post[:, 1] == 1, 0],
#                                         bins = np.linspace(0, max_t, 100))

            counts_2, bins = np.histogram(tmp_post[tmp_post[:, 1] == 1, 0],
                                          bins = np.linspace(0, max_t, nbins),
                                          density = True)
            
            if j == (n_post_params - 1) and row_tmp == 0 and col_tmp == 0:
                ax_tmp.hist(bins[:-1], 
                            bins, 
                            weights = choice_p_up_post * counts_2,
                            histtype = 'step',
                            alpha = 0.5, 
                            color = 'black',
                            edgecolor = 'black',
                            zorder = -1,
                            label = 'Posterior Predictive',
                            linewidth = hist_linewidth)
                
            else:
                ax_tmp.hist(bins[:-1], 
                            bins, 
                            weights = choice_p_up_post * counts_2,
                            histtype = 'step',
                            alpha = 0.5, 
                            color = 'black',
                            edgecolor = 'black',
                            linewidth = hist_linewidth,
                            zorder = -1)
                        
        
        if model_gt is not None:
#             counts, bins = np.histogram(tmp_true[tmp_true[:, 1] == 1, 0],
#                                     bins = np.linspace(0, max_t, 100))

            counts_2, bins = np.histogram(tmp_true[tmp_true[:, 1] == 1, 0],
                                          bins = np.linspace(0, max_t, nbins),
                                          density = True)

            if row_tmp == 0 and col_tmp == 0:
                ax_tmp.hist(bins[:-1], 
                            bins, 
                            weights = choice_p_up_true * counts_2,
                            histtype = 'step',
                            alpha = 0.5, 
                            color = 'red',
                            edgecolor = 'red',
                            zorder = -1,
                            linewidth = hist_linewidth,
                            label = 'Ground Truth Data')
                ax_tmp.legend(loc = 'lower right')
            else:
                ax_tmp.hist(bins[:-1], 
                        bins, 
                        weights = choice_p_up_true * counts_2,
                        histtype = 'step',
                        alpha = 0.5, 
                        color = 'red',
                        edgecolor = 'red',
                        zorder = -1,
                        linewidth = hist_linewidth)
        
        if ground_truths_data is not None:
            counts_2, bins = np.histogram(ground_truths_data[i, ground_truths_data[i, :, 1] == 1, 0],
                                          bins = np.linspace(0, max_t, nbins),
                                          density = True)
            
            choice_p_up_true_dat = np.sum(ground_truths_data[i, :, 1] == 1) / ground_truths_data[i].shape[0]

            
            if row_tmp == 0 and col_tmp == 0:
                ax_tmp.hist(bins[:-1], 
                            bins, 
                            weights = choice_p_up_true_dat * counts_2,
                            histtype = 'step',
                            alpha = 0.5, 
                            color = 'blue',
                            edgecolor = 'blue',
                            zorder = -1,
                            linewidth = hist_linewidth,
                            label = 'Dataset')
                ax_tmp.legend(loc = 'lower right')
            else:
                ax_tmp.hist(bins[:-1], 
                        bins, 
                        weights = choice_p_up_true_dat * counts_2,
                        histtype = 'step',
                        alpha = 0.5, 
                        color = 'blue',
                        edgecolor = 'blue',
                        linewidth = hist_linewidth,
                        zorder = -1)
            
            
             
        #ax.invert_xaxis()
        if rows > 1 and cols > 1:
            ax_tmp = ax[row_tmp, col_tmp].twinx()
        elif (rows == 1 and cols > 1) or (rows > 1 and cols == 1):
            ax_tmp = ax[i].twinx()
        else:
            ax_tmp = ax.twinx()
            
        ax_tmp.set_ylim(ylimit, -ylimit)
        ax_tmp.set_yticks([])
        
        if posterior_samples is not None:
#             counts, bins = np.histogram(tmp_post[tmp_post[:, 1] == -1, 0],
#                             bins = np.linspace(0, max_t, 100))

            counts_2, bins = np.histogram(tmp_post[tmp_post[:, 1] == -1, 0],
                                          bins = np.linspace(0, max_t, nbins),
                                          density = True)
            ax_tmp.hist(bins[:-1], 
                        bins, 
                        weights = (1 - choice_p_up_post) * counts_2,
                        histtype = 'step',
                        alpha = 0.5, 
                        color = 'black',
                        edgecolor = 'black',
                        linewidth = hist_linewidth,
                        zorder = -1)
            
        if model_gt is not None:
#             counts, bins = np.histogram(tmp_true[tmp_true[:, 1] == -1, 0],
#                                     bins = np.linspace(0, max_t, 100))

            counts_2, bins = np.histogram(tmp_true[tmp_true[:, 1] == -1, 0],
                                          bins = np.linspace(0, max_t, nbins),
                                          density = True)
            ax_tmp.hist(bins[:-1], 
                        bins, 
                        weights = (1 - choice_p_up_true) * counts_2,
                        histtype = 'step',
                        alpha = 0.5, 
                        color = 'red',
                        edgecolor = 'red',
                        linewidth = hist_linewidth,
                        zorder = -1)
        
        
        # -- new stuff
        
        if ground_truths_data is not None:
            counts_2, bins = np.histogram(ground_truths_data[i, ground_truths_data[i, :, 1] == - 1, 0],
                                          bins = np.linspace(0, max_t, nbins),
                                          density = True)
            
            #choice_p_up_true_dat = np.sum(ground_truths_data[i, :, 1] == 1) / ground_truths_data[i].shape[0]

            
            ax_tmp.hist(bins[:-1], 
                        bins, 
                        weights = (1 - choice_p_up_true_dat) * counts_2,
                        histtype = 'step',
                        alpha = 0.5, 
                        color = 'blue',
                        edgecolor = 'blue',
                        linewidth = hist_linewidth,
                        zorder = -1)

        
        # Plot posterior samples of bounds and slopes (model)
        if show_model:
            if posterior_samples is not None:
                for j in range(n_post_params):
                    if model_fitted == 'weibull_cdf' or model_fitted == 'weibull_cdf2' or model_fitted == 'weibull_cdf_concave':
                        b = posterior_samples[i, idx[j], 1] * bf.weibull_cdf(t = t_s, 
                                                                             alpha = posterior_samples[i, idx[j], 4],
                                                                             beta = posterior_samples[i, idx[j], 5])
                    if model_fitted == 'angle' or model_fitted == 'angle2':
                        b = np.maximum(posterior_samples[i, idx[j], 1] + bf.angle(t = t_s, 
                                                                                  theta = posterior_samples[i, idx[j], 4]), 0)
                    if model_fitted == 'ddm':
                        b = posterior_samples[i, idx[j], 1] * np.ones(t_s.shape[0])


                    start_point_tmp = - posterior_samples[i, idx[j], 1] + \
                                      (2 * posterior_samples[i, idx[j], 1] * posterior_samples[i, idx[j], 2])

                    slope_tmp = posterior_samples[i, idx[j], 0]

                    if rows > 1 and cols > 1:
                        ax[row_tmp, col_tmp].plot(t_s + posterior_samples[i, idx[j], 3], b, 'black',
                                                  t_s + posterior_samples[i, idx[j], 3], - b, 'black', 
                                                  alpha = 0.05,
                                                  zorder = 1000,
                                                  linewidth = posterior_linewidth,)
                    elif (rows == 1 and cols > 1) or (rows > 1 and cols == 1):
                        ax[i].plot(t_s + posterior_samples[i, idx[j], 3], b, 'black',
                                   t_s + posterior_samples[i, idx[j], 3], - b, 'black', 
                                   alpha = 0.05,
                                   zorder = 1000,
                                   linewidth = posterior_linewidth,)
                    else:
                        ax.plot(t_s + posterior_samples[i, idx[j], 3], b, 'black',
                                t_s + posterior_samples[i, idx[j], 3], - b, 'black', 
                                alpha = 0.05,
                                zorder = 1000,
                                linewidth = posterior_linewidth)

                    for m in range(len(t_s)):
                        if (start_point_tmp + (slope_tmp * t_s[m])) > b[m] or (start_point_tmp + (slope_tmp * t_s[m])) < -b[m]:
                            maxid = m
                            break
                        maxid = m

                    if rows > 1 and cols > 1:
                        ax[row_tmp, col_tmp].plot(t_s[:maxid] + posterior_samples[i, idx[j], 3],
                                                  start_point_tmp + slope_tmp * t_s[:maxid], 
                                                  c = 'black', 
                                                  alpha = 0.05,
                                                  zorder = 1000,
                                                  linewidth = posterior_linewidth,)
                        if j == (n_post_params - 1):
                            ax[row_tmp, col_tmp].plot(t_s[:maxid] + posterior_samples[i, idx[j], 3],
                                                      start_point_tmp + slope_tmp * t_s[:maxid], 
                                                      c = 'black', 
                                                      alpha = 0.05,
                                                      zorder = 1000,
                                                      linewidth = posterior_linewidth,
                                                      label = 'Model Samples')
                            
                    elif (rows == 1 and cols > 1) or (rows > 1 and cols == 1):
                        ax[i].plot(t_s[:maxid] + posterior_samples[i, idx[j], 3],
                                   start_point_tmp + slope_tmp * t_s[:maxid], 
                                   'black', 
                                   alpha = 0.05,
                                   zorder = 1000,
                                   linewidth = posterior_linewidth)
                        
                        if j == (n_post_params - 1):
                            ax[i].plot(t_s[:maxid] + posterior_samples[i, idx[j], 3],
                                       start_point_tmp + slope_tmp * t_s[:maxid], 
                                       c = 'black', 
                                       alpha = 0.05,
                                       linewidth = posterior_linewidth,
                                       zorder = 1000,
                                       label = 'Model Samples')

                    else:
                        ax.plot(t_s[:maxid] + posterior_samples[i, idx[j], 3],
                                start_point_tmp + slope_tmp * t_s[:maxid], 
                                'black', 
                                alpha = 0.05,
                                linewidth = posterior_linewidth,
                                zorder = 1000)
                        if j == (n_post_params - 1):
                            ax.plot(t_s[:maxid] + posterior_samples[i, idx[j], 3],
                                    start_point_tmp + slope_tmp * t_s[:maxid], 
                                    'black', 
                                    alpha = 0.05,
                                    linewidth = posterior_linewidth,
                                    zorder = 1000,
                                    label = 'Model Samples')
                            
                            
                    if rows > 1 and cols > 1:
                        ax[row_tmp, col_tmp].axvline(x = posterior_samples[i, idx[j], 3], 
                                                     ymin = - 2, 
                                                     ymax = 2, 
                                                     c = 'black', 
                                                     linestyle = '--',
                                                     linewidth = posterior_linewidth,
                                                     alpha = 0.05)
                        
                    elif (rows == 1 and cols > 1) or (rows > 1 and cols == 1):
                        ax[i].axvline(x = posterior_samples[i, idx[j], 3],
                                                            ymin = - 2,
                                                            ymax = 2,
                                                            c = 'black',
                                                            linestyle = '--',
                                                            linewidth = posterior_linewidth,
                                                            alpha = 0.05)
                    else:
                        ax.axvline(x = posterior_samples[i, idx[j], 3], 
                                   ymin = -2, 
                                   ymax = 2, 
                                   c = 'black', 
                                   linestyle = '--',
                                   linewidth = posterior_linewidth,
                                   alpha = 0.05)
                            
        # Plot ground_truths bounds
        if show_model and model_gt is not None:
            if model_gt == 'weibull_cdf' or model_gt == 'weibull_cdf2' or model_gt == 'weibull_cdf_concave':
                b = ground_truths_parameters[i, 1] * bf.weibull_cdf(t = t_s,
                                                         alpha = ground_truths_parameters[i, 4],
                                                         beta = ground_truths_parameters[i, 5])

            if model_gt == 'angle' or model_gt == 'angle2':
                b = np.maximum(ground_truths_parameters[i, 1] + bf.angle(t = t_s, theta = ground_truths_parameters[i, 4]), 0)

            if model_gt == 'ddm':
                b = ground_truths_parameters[i, 1] * np.ones(t_s.shape[0])

            start_point_tmp = - ground_truths_parameters[i, 1] + \
                              (2 * ground_truths_parameters[i, 1] * ground_truths_parameters[i, 2])
            slope_tmp = ground_truths_parameters[i, 0]

            if rows > 1 and cols > 1:
                if row_tmp == 0 and col_tmp == 0:
                    ax[row_tmp, col_tmp].plot(t_s + ground_truths_parameters[i, 3], b, 'red', 
                                              alpha = 1, 
                                              linewidth = gt_linewidth, 
                                              zorder = 1000)
                    ax[row_tmp, col_tmp].plot(t_s + ground_truths_parameters[i, 3], -b, 'red', 
                                              alpha = 1,
                                              linewidth = 3,
                                              zorder = 1000, 
                                              label = 'Grund Truth Model')
                    ax[row_tmp, col_tmp].legend(loc = 'upper right')
                else:
                    ax[row_tmp, col_tmp].plot(t_s + ground_truths_parameters[i, 3], b, 'red', 
                              t_s + ground_truths_parameters[i, 3], -b, 'red', 
                              alpha = 1,
                              linewidth = gt_linewidth,
                              zorder = 1000)
                    
            elif (rows == 1 and cols > 1) or (rows > 1 and cols == 1):
                if row_tmp == 0 and col_tmp == 0:
                    ax[i].plot(t_s + ground_truths_parameters[i, 3], b, 'red', 
                                              alpha = 1, 
                                              linewidth = gt_linewidth, 
                                              zorder = 1000)
                    ax[i].plot(t_s + ground_truths_parameters[i, 3], -b, 'red', 
                                              alpha = 1,
                                              linewidth = gt_linewidth,
                                              zorder = 1000, 
                                              label = 'Grund Truth Model')
                    ax[i].legend(loc = 'upper right')
                else:
                    ax[i].plot(t_s + ground_truths_parameters[i, 3], b, 'red', 
                              t_s + ground_truths_parameters[i, 3], -b, 'red', 
                              alpha = 1,
                              linewidth = gt_linewidth,
                              zorder = 1000)
            else:
                ax.plot(t_s + ground_truths_parameters[i, 3], b, 'red', 
                        alpha = 1, 
                        linewidth = gt_linewidth, 
                        zorder = 1000)
                ax.plot(t_s + ground_truths_parameters[i, 3], -b, 'red', 
                        alpha = 1,
                        linewidth = gt_linewidth,
                        zorder = 1000,
                        label = 'Ground Truth Model')
                #print('passed through legend part')
                #print(row_tmp)
                #print(col_tmp)
                ax.legend(loc = 'upper right')

            # Ground truth slope:
            for m in range(len(t_s)):
                if (start_point_tmp + (slope_tmp * t_s[m])) > b[m] or (start_point_tmp + (slope_tmp * t_s[m])) < -b[m]:
                    maxid = m
                    break
                maxid = m

            # print('maxid', maxid)
            if rows > 1 and cols > 1:
                ax[row_tmp, col_tmp].plot(t_s[:maxid] + ground_truths_parameters[i, 3], 
                                          start_point_tmp + slope_tmp * t_s[:maxid], 
                                          'red', 
                                          alpha = 1, 
                                          linewidth = gt_linewidth, 
                                          zorder = 1000)

                ax[row_tmp, col_tmp].set_zorder(ax_tmp.get_zorder() + 1)
                ax[row_tmp, col_tmp].patch.set_visible(False)
            elif (rows == 1 and cols > 1) or (rows > 1 and cols == 1):
                ax[i].plot(t_s[:maxid] + ground_truths_parameters[i, 3], 
                                          start_point_tmp + slope_tmp * t_s[:maxid], 
                                          'red', 
                                          alpha = 1, 
                                          linewidth = gt_linewidth, 
                                          zorder = 1000)

                ax[i].set_zorder(ax_tmp.get_zorder() + 1)
                ax[i].patch.set_visible(False)
            else:
                ax.plot(t_s[:maxid] + ground_truths_parameters[i, 3], 
                        start_point_tmp + slope_tmp * t_s[:maxid], 
                        'red', 
                        alpha = 1, 
                        linewidth = gt_linewidth, 
                        zorder = 1000)

                ax.set_zorder(ax_tmp.get_zorder() + 1)
                ax.patch.set_visible(False)
               
        # Set plot title
        title_tmp = ''
        
        if model_gt is not None:
            for k in range(len(ax_titles)):
                title_tmp += ax_titles[k] + ': '
                title_tmp += str(round(ground_truths_parameters[i, k], 2)) + ', ' 

        if rows > 1 and cols > 1:
            if row_tmp == rows:
                ax[row_tmp, col_tmp].set_xlabel('rt', 
                                                 fontsize = 20);
            ax[row_tmp, col_tmp].set_ylabel('', 
                                            fontsize = 20);


            ax[row_tmp, col_tmp].set_title(title_tmp,
                                           fontsize = 24)
            ax[row_tmp, col_tmp].tick_params(axis = 'y', size = 20)
            ax[row_tmp, col_tmp].tick_params(axis = 'x', size = 20)

            # Some extra styling:
            if model_gt is not None:
                ax[row_tmp, col_tmp].axvline(x = ground_truths_parameters[i, 3], ymin = -2, ymax = 2, c = 'red', linestyle = '--')
                ax[row_tmp, col_tmp].axhline(y = 0, xmin = 0, xmax = ground_truths_parameters[i, 3] / max_t, c = 'red',  linestyle = '--')
        
        elif (rows == 1 and cols > 1) or (rows > 1 and cols == 1):
            if row_tmp == rows:
                ax[i].set_xlabel('rt', 
                                 fontsize = 20);
            ax[i].set_ylabel('', 
                             fontsize = 20);

            ax[i].set_title(title_tmp,
                            fontsize = 24)
            
            ax[i].tick_params(axis = 'y', size = 20)
            ax[i].tick_params(axis = 'x', size = 20)

            # Some extra styling:
            if model_gt is not None:
                ax[i].axvline(x = ground_truths_parameters[i, 3], ymin = -2, ymax = 2, c = 'red', linestyle = '--')
                ax[i].axhline(y = 0, xmin = 0, xmax = ground_truths_parameters[i, 3] / max_t, c = 'red',  linestyle = '--')
        
        else:
            if row_tmp == rows:
                ax.set_xlabel('rt', 
                              fontsize = 20);
            ax.set_ylabel('', 
                          fontsize = 20);

            ax.set_title(title_tmp,
                         fontsize = 24)

            ax.tick_params(axis = 'y', size = 20)
            ax.tick_params(axis = 'x', size = 20)

            # Some extra styling:
            if model_gt is not None:
                ax.axvline(x = ground_truths_parameters[i, 3], ymin = -2, ymax = 2, c = 'red', linestyle = '--')
                ax.axhline(y = 0, xmin = 0, xmax = ground_truths_parameters[i, 3] / max_t, c = 'red',  linestyle = '--')

    if rows > 1 and cols > 1:
        for i in range(n_plots, rows * cols, 1):
            row_tmp = int(np.floor(i / cols))
            col_tmp = i - (cols * row_tmp)
            ax[row_tmp, col_tmp].axis('off')

    plt.tight_layout(rect = [0, 0.03, 1, 0.9])
    
    if save == True:
        plt.savefig('figures/' + 'hierarchical_model_plot_' + model_gt + '_' + datatype + '.svg',
                    format = 'svg', 
                    transparent = True,
                    frameon = False)
        plt.close()
    
    return plt.show()


def posterior_predictive_plot(posterior_samples = None,
                              ground_truths_parameters = None,
                              ground_truths_data = None,
                              n_plots = 9,
                              cols = 3,
                              model_fitted = 'angle',
                              model_gt = 'angle',
                              datatype = 'single_subject',
                              input_hddm_trace = True,
                              n_post_params = 100,
                              max_t = 20,
                              samples_by_param = 10,
                              xlimit = 10,
                              bin_size = 0.025,
                              hist_linewidth = 3,
                              save = False):
    
    
#                 counts_2, bins = np.histogram(tmp_true[tmp_true[:, 1] == -1, 0],
#                                           bins = np.linspace(0, max_t, 100),
#                                           density = True)

    if save == True:
        matplotlib.rcParams['text.usetex'] = True
        #matplotlib.rcParams['pdf.fonttype'] = 42
        matplotlib.rcParams['svg.fonttype'] = 'none'
    
    if model_gt is None and ground_truths_data is None and posterior_samples is None:
        return 'No ground truth model was supplied, no dataset was supplied and no posterior sample was supplied. Nothin to plot' 
    
    # Inputs are hddm_traces --> make plot ready
    if input_hddm_trace and posterior_samples is not None:
        if datatype == 'hierarchical':
            posterior_samples = _make_trace_plotready_hierarchical(posterior_samples, 
                                                                   model = model_fitted)
            n_plots = posterior_samples.shape[0]
#             print(posterior_samples)
            
        if datatype == 'single_subject':
            posterior_samples = _make_trace_plotready_single_subject(posterior_samples, 
                                                                     model = model_fitted)
        if datatype == 'condition':
            posterior_samples = _make_trace_plotready_condition(posterior_samples, 
                                                                model = model_fitted)
            n_plots = posterior_samples.shape[0]
            #print(posterior_samples)
            #n_plots = posterior_samples.shape[0]
            
    if n_plots == 1:
        rows = 1
        cols = 1
    
    nbins = int((2 * max_t) / bin_size)
        # Taking care of special case with 1 plot
    if n_plots == 1:
        if model_gt is not None:
            ground_truths_parameters = np.expand_dims(ground_truths_parameters, 0)
        if posterior_samples is not None:
            posterior_samples = np.expand_dims(posterior_samples, 0)
        if ground_truths_data is not None:
            ground_truths_data = np.expand_dims(ground_truths_data, 0)
         
    
#     matplotlib.rcParams['text.usetex'] = True
#     #matplotlib.rcParams['pdf.fonttype'] = 42
#     matplotlib.rcParams['svg.fonttype'] = 'none'
    
    rows = int(np.ceil(n_plots / cols))
    sns.set(style = "white", 
            palette = "muted", 
            color_codes = True,
            font_scale = 2)

    fig, ax = plt.subplots(rows, cols, 
                           figsize = (10, 10), 
                           sharex = False, 
                           sharey = False)
    
    fig.suptitle('Posterior Predictive: ' + model_fitted.upper(),
                 fontsize = 24)
    
    sns.despine(right = True)
#     tmp_simulator = simulator(model = model, 
#                               n_samples = 20000,
#                               bin_dim = None)
    
    for i in range(n_plots):
        row_tmp = int(np.floor(i / cols))
        col_tmp = i - (cols * row_tmp)
        
        post_tmp = np.zeros((n_post_params * samples_by_param, 2))
        idx = np.random.choice(posterior_samples.shape[1], 
                               size = n_post_params, 
                               replace = False)

        # Run Model simulations for posterior samples
        for j in range(n_post_params):
            out = simulator(theta = posterior_samples[i, idx[j], :], 
                            model = model_fitted,
                            n_samples = samples_by_param,
                            bin_dim = None)
          
            post_tmp[(samples_by_param * j):(samples_by_param * (j + 1)), :] = np.concatenate([out[0], out[1]], axis = 1)
        
        # Run Model simulations for true parameters
        if model_gt is not None:
            out = simulator(theta = ground_truths_parameters[i, :],
                            model = model_gt,
                            n_samples = 20000,
                            bin_dim = None)
  
            gt_tmp = np.concatenate([out[0], out[1]], axis = 1)
            gt_color = 'red'
            #print('passed through')
        else:
            gt_tmp = ground_truths_data[i]
            gt_color = 'blue'
        
        if rows > 1 and cols > 1:
            
            sns.distplot(post_tmp[:, 0] * post_tmp[:, 1], 
                         bins = np.linspace(-max_t, max_t, nbins), #50, 
                         kde = False, 
                         rug = False, 
                         hist_kws = {'alpha': 1, 
                                     'color': 'black',
                                     'histtype': 'step', 
                                     'density': 1, 
                                     'edgecolor': 'black',
                                     'linewidth': hist_linewidth},
                         ax = ax[row_tmp, col_tmp]);

            sns.distplot(gt_tmp[:, 0] * gt_tmp[:, 1], 
                         hist_kws = {'alpha': 0.5, 
                                     'color': gt_color, 
                                     'density': 1, 
                                     'edgecolor': gt_color,  
                                     'histtype': 'step',
                                     'linewidth': hist_linewidth}, 
                         bins = np.linspace(-max_t, max_t, nbins), #50, 
                         kde = False, 
                         rug = False,
                         ax = ax[row_tmp, col_tmp])
            
        elif (rows == 1 and cols > 1) or (rows > 1 and cols == 1):
            
            sns.distplot(post_tmp[:, 0] * post_tmp[:, 1], 
                         bins = np.linspace(-max_t, max_t, nbins), #50, 
                         kde = False, 
                         rug = False, 
                         hist_kws = {'alpha': 1, 
                                     'color': 'black',
                                     'histtype': 'step', 
                                     'density': 1, 
                                     'edgecolor': 'black',
                                     'linewidth': hist_linewidth},
                         ax = ax[i]);

            sns.distplot(gt_tmp[:, 0] * gt_tmp[:, 1], 
                         hist_kws = {'alpha': 0.5, 
                                     'color': gt_color, 
                                     'density': 1, 
                                     'edgecolor': gt_color, 
                                     'histtype': 'step',
                                     'linewidth': hist_linewidth}, 
                         bins = np.linspace(-max_t, max_t, nbins), #50, 
                         kde = False, 
                         rug = False,
                         ax = ax[i])
            
        else:
            
            sns.distplot(post_tmp[:, 0] * post_tmp[:, 1], 
                         bins = np.linspace(-max_t, max_t, nbins), #50, 
                         kde = False,
                         rug = False,
                         hist_kws = {'alpha': 1, 
                                     'color': 'black', 
                                     'histtype': 'step', 
                                     'density': 1, 
                                     'edgecolor': 'black',
                                     'linewidth': hist_linewidth},
                         ax = ax);
            
            sns.distplot(gt_tmp[:, 0] * gt_tmp[:, 1], 
                         hist_kws = {'alpha': 0.5, 
                                     'color': gt_color, 
                                     'density': 1,
                                     'edgecolor': gt_color,  
                                     'histtype':'step',
                                     'linewidth': hist_linewidth}, 
                         bins = np.linspace(-max_t, max_t, nbins), #50, 
                         kde = False, 
                         rug = False,
                         ax = ax)
        
#         if rows > 1 and cols > 1:
#             ax[row_tmp, col_tmp].set_xlim(0, max_t)
#             ax[row_tmp, col_tmp].set_ylim(-ylimit, ylimit)
#         elif (rows == 1 and cols > 1) or (rows > 1 and cols == 1):
#             ax[i].set_xlim(0, max_t)
#             ax[i].set_ylim(-ylimit, ylimit)
#         else:
#             ax.set_xlim(0, max_t)
#             ax.set_ylim(-ylimit, ylimit)
        
        if rows > 1 and cols > 1:
            tmp_ax = ax[row_tmp, col_tmp]
        elif (rows == 1 and cols > 1) or (rows > 1 and cols == 1):
            tmp_ax = ax[i]
        else:
            tmp_ax = ax
            
        tmp_ax.set_xlim(-xlimit, xlimit)
            
        if row_tmp == 0 and col_tmp == 0:
            if model_gt is not None:
                label_0 = 'GROUND TRUTH'
            else:
                label_0 = 'DATA'
            tmp_ax.legend(labels = ['POSTERIOR PREDICTIVE', label_0], 
                          fontsize = 12, 
                          loc = 'upper right')
            
#             ax[row_tmp, col_tmp].legend(labels = [model_fitted, 'posterior'], 
#                                         fontsize = 12, loc = 'upper right')
        
        if row_tmp == (rows - 1):
            tmp_ax.set_xlabel('RT', 
                                            fontsize = 24);
#             ax[row_tmp, col_tmp].set_xlabel('RT', 
#                                             fontsize = 14);
        
        if col_tmp == 0:
            tmp_ax.set_ylabel('Density', 
                                            fontsize = 24);
#             ax[row_tmp, col_tmp].set_ylabel('Density', 
#                                             fontsize = 14);
        
#         ax[row_tmp, col_tmp].set_title(ax_titles[i],
#                                        fontsize = 16)
        tmp_ax.tick_params(axis = 'y', size = 22)
        tmp_ax.tick_params(axis = 'x', size = 22)
        
#         ax[row_tmp, col_tmp].tick_params(axis = 'y', size = 12)
#         ax[row_tmp, col_tmp].tick_params(axis = 'x', size = 12)
        
        if rows > 1 and cols > 1:
            ax[row_tmp, col_tmp] = tmp_ax
        elif (rows == 1 and cols > 1) or (rows > 1 and cols == 1):
            ax[i] = tmp_ax
        else:
            ax = tmp_ax
        
    if rows > 1 and cols > 1:
        for i in range(n_plots, rows * cols, 1):
            row_tmp = int(np.floor(i / cols))
            col_tmp = i - (cols * row_tmp)
            ax[row_tmp, col_tmp].axis('off')
            
            
    if save == True:
        plt.savefig('figures/' + 'posterior_predictive_plot_' + model_gt + '_' + datatype + '.svg',
                    format = 'svg', 
                    transparent = True,
                    frameon = False)
        plt.close()

    return plt.show()

def caterpillar_plot(posterior_samples = [],
                     ground_truths = None,
                     model = 'angle',
                     datatype = 'hierarchical', # 'hierarchical', 'single_subject', 'condition'
                     drop_sd = True,
                     save = False):
    
    if save == True:
        matplotlib.rcParams['text.usetex'] = True
        #matplotlib.rcParams['pdf.fonttype'] = 42
        matplotlib.rcParams['svg.fonttype'] = 'none'
    
    
    sns.set(style = "white", 
        palette = "muted", 
        color_codes = True,
        font_scale = 2)

    fig, ax = plt.subplots(1, 1, 
                           figsize = (10, 10), 
                           sharex = False, 
                           sharey = False)
    
    my_suptitle = fig.suptitle('Caterpillar plot: ' + model.upper().replace('_', '-'), fontsize = 40)
    sns.despine(right = True)
    
    trace = posterior_samples.copy()
    
    
    if ground_truths is not None:
        cnt = 0
        #ground_truths = ground_truths.copy()
        gt_dict = {}
        
        if datatype == 'single_subject':
            for v in config[model]['params']:
                gt_dict[v] = ground_truths[cnt]
                cnt += 1

        if datatype == 'hierarchical':
            gt_dict = ground_truths
#             tmp = {}
#             tmp['subj'] = ground_truths[1]
#             tmp['global_sds'] = ground_truths[2]
#             tmp['global_means'] = ground_truths[3]

#             ground_truths = tmp

#             gt_dict = {}
#             for param in ground_truths['subj'].keys():
#                 for i in range(ground_truths['subj'].shape[0]):
#                     gt_dict[param + '_subj.' + str(i) + '.0'] = ground_truths['subj'][param][i]
#             for param in ground_truths['global_means'].keys():
#                 gt_dict[param] = ground_truths['global_means'][param][0]

        if datatype == 'condition':
            gt_dict = ground_truths
             
    ecdfs = {}
    plot_vals = {} # [0.01, 0.9], [0.01, 0.99], [mean]
    for k in trace.keys():
        
        if 'std' in k and drop_sd:
            pass
        else:
            if '_trans' in k:
                label_tmp = k.replace('_trans', '')
                trace[label_tmp] = 1 / (1 + np.exp(- trace[k]))
                k = label_tmp
                #print(trace[k].mean())
            #print(k)
            #print(trace[k])
            ok_ = 1
            
            k_old = k
            k = k.replace('_', '-')
            
            if drop_sd == True:
                if 'sd' in k:
                    ok_ = 0
            if ok_:
                ecdfs[k] = ECDF(trace[k_old])
                tmp_sorted = sorted(trace[k_old])
                _p01 =  tmp_sorted[np.sum(ecdfs[k](tmp_sorted) <= 0.01) - 1]
                _p99 = tmp_sorted[np.sum(ecdfs[k](tmp_sorted) <= 0.99) - 1]
                _p1 = tmp_sorted[np.sum(ecdfs[k](tmp_sorted) <= 0.1) - 1]
                _p9 = tmp_sorted[np.sum(ecdfs[k](tmp_sorted) <= 0.9) - 1]
                _pmean = trace[k_old].mean()
                plot_vals[k] = [[_p01, _p99], [_p1, _p9], _pmean]
        
    x = [plot_vals[k][2] for k in plot_vals.keys()]
    ax.scatter(x, plot_vals.keys(), c = 'black', marker = 's', alpha = 0)
    for k in plot_vals.keys():
        k = k.replace('_', '-')
        ax.plot(plot_vals[k][1], [k, k], c = 'grey', zorder = -1, linewidth = 5)
        ax.plot(plot_vals[k][0] , [k, k], c = 'black', zorder = -1)
        if ground_truths is not None:
            ax.scatter(gt_dict[k.replace('-', '_')], k,  c = 'red', marker = "|")
            
    if save == True:
        plt.savefig('figures/' + 'caterpillar_plot_' + model + '_' + datatype + '.svg',
                    format = 'svg', 
                    transparent = True,
                    frameon = False)
        #plt.close()

    return plt.show()

# Posterior Pair Plot
def posterior_pair_plot(posterior_samples = [],
                        axes_limits = 'model', # 'model', 'samples'
                        height = 10,
                        aspect = 1,
                        n_subsample = 1000,
                        ground_truths = [],
                        model = None,
                        save = False):
    
    if save == True:
        matplotlib.rcParams['text.usetex'] = True
        #matplotlib.rcParams['pdf.fonttype'] = 42
        matplotlib.rcParams['svg.fonttype'] = 'none'
    
    
    # some preprocessing
    #posterior_samples = posterior_samples.get_traces().copy()
    posterior_samples['z'] = 1 / ( 1 + np.exp(- posterior_samples['z_trans']))
    posterior_samples = posterior_samples.drop('z_trans', axis = 1)

    g = sns.PairGrid(posterior_samples.sample(n_subsample), 
                     height = height / len(list(posterior_samples.keys())),
                     aspect = 1,
                     diag_sharey = False)
    g = g.map_diag(sns.kdeplot, color = 'black', shade = False) # shade = True, 
    g = g.map_lower(sns.kdeplot, 
                    shade_lowest = False,
                    n_levels = 50,
                    shade = False,
                    cmap = 'Purples_d') # 'Greys'
    
    for i, j in zip(*np.triu_indices_from(g.axes, 1)):
        g.axes[i, j].set_visible(False)
    
    
    if axes_limits == 'model':
        xlabels,ylabels = [],[]

        for ax in g.axes[-1, :]:
            xlabel = ax.xaxis.get_label_text()
            xlabels.append(xlabel)

        for ax in g.axes[:, 0]:
            ylabel = ax.yaxis.get_label_text()
            ylabels.append(ylabel)

        for i in range(len(xlabels)):
            for j in range(len(ylabels)):
                g.axes[j,i].set_xlim(config[model]['param_bounds'][0][config[model]['params'].index(xlabels[i])], 
                                     config[model]['param_bounds'][1][config[model]['params'].index(xlabels[i])])
                g.axes[j,i].set_ylim(config[model]['param_bounds'][0][config[model]['params'].index(ylabels[j])], 
                                     config[model]['param_bounds'][1][config[model]['params'].index(ylabels[j])])

    
    for ax in g.axes.flat:
        plt.setp(ax.get_xticklabels(), rotation = 45)

    my_suptitle = g.fig.suptitle(model.upper(), 
                                 y = 1.03, 
                                 fontsize = 24)
    
    # If ground truth is available add it in:
    if ground_truths is not None:
        for i in range(g.axes.shape[0]):
            for j in range(i + 1, g.axes.shape[0], 1):
                g.axes[j,i].plot(ground_truths[config[model]['params'].index(xlabels[i])], 
                                 ground_truths[config[model]['params'].index(ylabels[j])], 
                                 '.', 
                                 color = 'red',
                                 markersize = 10)

        for i in range(g.axes.shape[0]):
            g.axes[i,i].plot(ground_truths[i],
                             g.axes[i,i].get_ylim()[0], 
                             '.', 
                             color = 'red',
                             markersize = 10)
            
    if save == True:
        plt.savefig('figures/' + 'pair_plot_' + model + '_' + datatype + '.svg',
                    format = 'svg', 
                    transparent = True,
                    frameon = False)
        plt.close()
            
    # Show
    return plt.show(block = False)