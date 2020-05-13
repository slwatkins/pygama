#!/usr/bin/env python3
import os, json
import pandas as pd
import itertools
from collections import OrderedDict
from string import Formatter
from pathlib import Path
from parse import parse
from pprint import pprint

import pygama.utils as pu


class DataGroup:
    """
    A class to create an in-memory or on-disk set of files, according to the
    LEGEND data convention.  Typically requires a JSON config file with:
      - path to DAQ and LH5 directories
      - format strings for daq/lh5 files
      - partitions for the LH5 data directory
    
    Reference: https://docs.legend-exp.org/index.php/apps/files/?dir=/LEGEND%20Documents/Technical%20Documents/Analysis&fileid=9140#pdfviewer
    """
    def __init__(self, config=None, nfiles=None, load=False):
        """
        """
        # master table
        self.file_keys = None
        
        # typical usage: JSON config file
        if config is not None:
            self.set_config(os.path.expandvars(config))
            
        # limit number of files (useful for debug & testing)
        self.nfiles = nfiles
        
        # load a pre-existing set of keys.  should be True by default
        if load:
            print('load file_keys here')


    def set_config(self, config):
        """
        """
        with open(config) as f:
            self.config = json.load(f)
        
        # experiment name
        self.experiment = self.config['experiment']
    
        # experiment-specific runDB.  optional but recommended
        self.f_runDB = os.path.expandvars(self.config['runDB'])
        if os.path.exists(self.f_runDB):
            with open(self.f_runDB) as f:
                self.runDB = json.load(f, object_pairs_hook=OrderedDict)
                
        # experiment-specific fileDB (csv list of file keys)
        self.f_fileDB = os.path.expandvars(self.config['fileDB'])
                
        # set DAQ data directory
        self.daq_dir = os.path.expandvars(self.config['daq_dir'])
        self.daq_ignore = self.config['daq_ignore']
        if not os.path.isdir(self.daq_dir):
            print('Warning, DAQ directory not found:', self.daq_dir)
        
        # set LH5 data directory
        self.lh5_dir = os.path.expandvars(self.config['lh5_dir'])
        if not os.path.isdir(self.lh5_dir):
            print('Warning, LH5 directory not found:', self.lh5_dir)
        
        # get LH5 subdirectory names
        self.tier_dirs = self.config['tier_dirs']
        self.subsystems = self.config['subsystems']
        self.run_types = self.config['run_types']
        self.evt_dirs = self.config['evt_dirs']
        
        # get format strings for unique keys, DAQ files, and LH5 files
        self.unique_key = self.config['unique_key']
        self.daq_template = self.config['daq_template']
        self.lh5_template = self.config['lh5_template']

    
    def lh5_dir_setup(self, create=False):
        """
        view LH5 data directories.  if create is True, actually create them
        """
        dirs = []
        
        # directories for hit-level data
        t, r, s = self.tier_dirs, self.subsystems, self.run_types 
        for tier, subs, rtp in itertools.product(t, s, r):
            dirname = f'{self.lh5_dir}/{tier}/{subs}/{rtp}'
            print(dirname)
            dirs.append(dirname)
                
        # directories for event-level data
        for dir in self.evt_dirs:
            dirname = f'{self.lh5_dir}/{dir}'
            print(dirname)
            dirs.append(dirname)
            
        if create:
            ans = input('Create directories? (y/n)')
            if ans.lower() == 'y':
                for d in dirs:
                    Path(d).mkdir(parents=True, exist_ok=True)
            
        
    def scan_daq_dir(self, verbose=False):
        """
        scan the DAQ directory and build a DataFrame of file keys.
        don't make any experiment-specific choices here.
        """
        dt = self.daq_template
        di = self.daq_ignore
        
        file_keys = []
        stop_walk = False
        
        for path, folders, files in os.walk(self.daq_dir):
            
            for f in files:
                
                # in some cases, we need information from the path name
                if '/' in self.daq_template:
                    f_tmp = path.replace(self.daq_dir,'') + '/' + f
                else:
                    f_tmp = f
                
                # check if we should ignore this file
                if len(di) > 0 and any(ig in f_tmp for ig in di):
                    continue
                
                finfo = parse(self.daq_template, f_tmp)
                if finfo is not None:
                    finfo = finfo.named # convert to dict
                    finfo['daq_dir'] = path.replace(self.daq_dir,'') # sub-dir
                    finfo['daq_file'] = f
                    file_keys.append(finfo)                    
                
                # limit number of files (debug mode)
                if self.nfiles is not None and len(file_keys)==self.nfiles:
                    stop_walk = True
                if stop_walk:
                    break
            if stop_walk:
                break

        # create the main DataFrame
        self.file_keys = pd.DataFrame(file_keys)
        
        # grab the unique key and sort the DataFrame by it
        fk = lambda x: self.unique_key.format_map(x)
        self.file_keys['unique_key'] = self.file_keys.apply(fk, axis=1)
        
        # reorder cols to match the daq_template string
        cols = ['unique_key']
        cols.extend([fn for _,fn,_,_ in Formatter().parse(dt) if fn is not None])
        cols.extend(['daq_dir','daq_file'])
        self.file_keys = self.file_keys[cols]
        
        # convert cols to numeric dtypes where possible
        for col in self.file_keys.columns:
            try:
                self.file_keys[col] = pd.to_numeric(self.file_keys[col])
            except:
                pass
        # print(self.file_keys.dtypes)
                
        if verbose:
            print(self.file_keys.to_string())
            
            
    def save_keys(self, fname=None):
        """
        default: save the unique_key and the relative path to the DAQ file,
        as a CSV file.  this will probably change in the future, but at least 
        this way we can:
          - easily get a list of available DAQ files
          - regenerate the DataFrame from scan_daq_dir by parsing format string
        """
        if fname is None:
            fname = self.f_fileDB
        print('Saving file key list to: ', fname)
        
        df_keys = self.file_keys
        df_keys['rel_daq_path'] = df_keys['daq_dir'] + '/' + df_keys['daq_file']
    
        # export to csv
        df_keys[['unique_key','rel_daq_path']].to_csv(fname, index=False)


    def load_keys(self, fname=None):
        """
        load a list of file keys and parse data into columns according to 
        the format string
        """
        if fname is None:
            fname = self.f_fileDB
        print('Loading file key list from:', fname)
        
        df_keys = pd.read_csv(fname)
    
        dt = self.daq_template
        cols = [fn for _,fn,_,_ in Formatter().parse(dt) if fn is not None]
        
        def parse_key(row):
            """ extract variables from format string from daq_path """
            tmp = row['rel_daq_path'].split('/')
            daq_dir = '/'.join(t for t in tmp[:-1])
            daq_file = tmp[-1]
            unique_key = row['unique_key']
            if '/' in self.daq_template:
                finfo = parse(self.daq_template, row['rel_daq_path']).named
            else:
                finfo = parse(self.daq_template, daq_file).named
            row = pd.Series(finfo)
            row['unique_key'] = unique_key
            row['daq_dir'] = daq_dir
            row['daq_file'] = daq_file
            return row
            
        self.file_keys = df_keys.apply(parse_key, axis=1)
        
        # reorder cols to match the daq_template string
        cols = ['unique_key']
        cols.extend([fn for _,fn,_,_ in Formatter().parse(dt) if fn is not None])
        cols.extend(['daq_dir','daq_file'])
        self.file_keys = self.file_keys[cols]
        
    
    def save_df(self, fname=None):
        """
        save the current self.file_keys dataframe. If we've added extra columns
        specific to an experiment (outside this class), this will preserve them.
        """
        if fname is None:
            fname = self.f_fileDB
        print('Saving file key list to: ', fname)
        # self.file_keys.to_json(fname, indent=2)
        self.file_keys.to_hdf(fname, key='file_keys')
        
        
    def load_df(self, fname=None):
        """
        """
        if fname is None:
            fname = self.f_fileDB
        print('Loading file key list from:', fname)
        
        # self.file_keys = pd.read_json(fname)
        self.file_keys = pd.read_hdf(fname, key='file_keys')
        
        
    def get_lh5_cols(self):
        """
        compute the LH5 filenames.
        
        need to generate the file names, and then figure out which folder
        to store them in.  probably best to separate these tasks
        """
        if 'runtype' not in self.file_keys.columns:
            print("You must add a 'runtype' column to the file key DF.")
            exit()
        
        def get_files(row):
            tmp = row.to_dict()
            for tier in self.tier_dirs:
                
                # get filename
                tmp['tier'] = tier
                row[f'{tier}_file'] = self.lh5_template.format_map(tmp)
                
                # compute file path.  this is tricky
                path = f'/{tier}'
                
                # daq_to_raw outputs a file for each subsystem, and we 
                # handle this here by leaving a regex in the file string
                if self.subsystems != [""]: 
                    path += '/{sysn}'
                
                if row['runtype'] in self.run_types: 
                    path += f"/{row['runtype']}"
            
                row[f'{tier}_path'] = path
            return row
            
        self.file_keys = self.file_keys.apply(get_files, axis=1)
