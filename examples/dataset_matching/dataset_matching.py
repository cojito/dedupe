#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
This code demonstrates how to use dedupe with a comma separated values
(CSV) file. All operations are performed in memory, so will run very
quickly on datasets up to ~10,000 rows.

We start with a CSV file containing our messy data. In this example,
it is listings of early childhood education centers in Chicago
compiled from several different sources.

The output will be a CSV with our clustered results.

For larger datasets, see our [mysql_example](http://open-city.github.com/dedupe/doc/mysql_example.html)
"""

import os
import csv
import re
import collections
import logging
import optparse
from numpy import nan
import math

import AsciiDammit

import dedupe

# ## Logging

# Dedupe uses Python logging to show or suppress verbose output. Added for convenience.
# To enable verbose logging, run `python examples/csv_example/csv_example.py -v`

optp = optparse.OptionParser()
optp.add_option('-v', '--verbose', dest='verbose', action='count',
                help='Increase verbosity (specify multiple times for more)'
                )
(opts, args) = optp.parse_args()
log_level = logging.WARNING 
if opts.verbose == 1:
    log_level = logging.INFO
elif opts.verbose >= 2:
    log_level = logging.DEBUG
logging.basicConfig(level=log_level)


# ## Setup

# Switch to our working directory and set up our input and out put paths,
# as well as our settings and training file locations
os.chdir('./examples/dataset_matching/')
output_file = 'data_matching_output.csv'
settings_file = 'data_matching_learned_settings'
training_file = 'data_matching_training.json'

def comparePrice(price_1, price_2) :
    if price_1 == 0 :
        return nan
    elif price_2 == 0 :
        return nan
    else :
        return abs(math.log(price_1) - math.log(price_2))

def preProcess(column):
    """
    Do a little bit of data cleaning with the help of [AsciiDammit](https://github.com/tnajdek/ASCII--Dammit) 
    and Regex. Things like casing, extra spaces, quotes and new lines can be ignored.
    """

    column = AsciiDammit.asciiDammit(column)
    column = re.sub('\n', ' ', column)
    column = re.sub('-', '', column)
    column = re.sub('/', ' ', column)
    column = re.sub("'", '', column)
    column = re.sub(",", '', column)
    column = re.sub(":", ' ', column)
    column = re.sub('  +', ' ', column)
    column = column.strip().strip('"').strip("'").lower().strip()
    return column


def readData(filename):
    """
    Read in our data from a CSV file and create a dictionary of records, 
    where the key is a unique record ID and each value is a 
    [frozendict](http://code.activestate.com/recipes/414283-frozen-dictionaries/) 
    (hashable dictionary) of the row fields.
    """

    data_d = {}

    with open(filename) as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            clean_row = dict([(k, preProcess(v)) for (k, v) in row.items()])
            try :
                clean_row['price'] = float(clean_row['price'][1:])
            except ValueError :
                clean_row['price'] = 0
            data_d[filename + str(i)] = dedupe.core.frozendict(clean_row)

    return data_d

print 'importing data ...'
data_1 = readData('AbtBuy_Abt.csv')
data_2 = readData('AbtBuy_Buy.csv')

# ## Training

if os.path.exists(settings_file):
    print 'reading from', settings_file
    linker = dedupe.RecordLink(settings_file)

else:
    # To train dedupe, we feed it a random sample of records.
    data_sample = dedupe.dataSampleRecordLink(data_1, data_2, 150000)

    # Define the fields dedupe will pay attention to
    #
    # Notice how we are telling dedupe to use a custom field comparator
    # for the 'Zip' field. 
    fields = {
        'title': {'type': 'String'},
        'description': {'type': 'String',
                        'Has Missing' :True},
        'price': {'type' : 'Custom',
                  'comparator' : comparePrice,
                  'Has Missing' : True}}

    # Create a new linker object and pass our data model to it.
    linker = dedupe.RecordLink(fields,
                                data_sample)

    # If we have training data saved from a previous run of dedupe,
    # look for it an load it in.
    # __Note:__ if you want to train from scratch, delete the training_file
    if os.path.exists(training_file):
        print 'reading labeled examples from ', training_file
        linker.trainFromFile(training_file)

    # ## Active learning

    # Starts the training loop. Dedupe will find the next pair of records
    # it is least certain about and ask you to label them as duplicates
    # or not.

    # use 'y', 'n' and 'u' keys to flag duplicates
    # press 'f' when you are finished
    print 'starting active labeling...'
    dedupe.training.consoleLabel(linker)
    # When finished, save our training away to disk
    linker.writeTraining(training_file)

# ## Blocking

print 'blocking...'
# Initialize our blocker. We'll learn our blocking rules if we haven't
# loaded them from a saved settings file.
blocker = linker.blockingFunction()

# Save our weights and predicates to disk.  If the settings file
# exists, we will skip all the training and learning next time we run
# this file.
linker.writeSettings(settings_file)

# Load all the original data in to memory and place
# them in to blocks. Each record can be blocked in many ways, so for
# larger data, memory will be a limiting factor.

blocked_data = tuple(dedupe.blockDataRecordLinkdata_1, data_2, blocker))

# ## Clustering

# Find the threshold that will maximize a weighted average of our precision and recall. 
# When we set the recall weight to 2, we are saying we care twice as much
# about recall as we do precision.
#
# If we had more data, we would not pass in all the blocked data into
# this function but a representative sample.

threshold = linker.goodThreshold(blocked_data, recall_weight=3)

# `duplicateClusters` will return sets of record IDs that dedupe
# believes are all referring to the same entity.

print 'clustering...'
clustered_dupes = linker.duplicateClusters(blocked_data, threshold)

print '# duplicate sets', len(clustered_dupes)

# ## Writing Results

# Write our original data back out to a CSV with a new column called 
# 'Cluster ID' which indicates which records refer to each other.

cluster_membership = collections.defaultdict(lambda : 'x')
for (cluster_id, cluster) in enumerate(clustered_dupes):
    for record_id in cluster:
        cluster_membership[record_id] = cluster_id



with open(output_file, 'w') as f:
    writer = csv.writer(f)

    for fileno, filename in enumerate(('AbtBuy_Abt.csv', 'AbtBuy_Buy.csv')) :
        row_id = 0
        with open(filename) as f_input :
            reader = csv.reader(f_input)

            heading_row = reader.next()
            heading_row.insert(0, 'source file')
            heading_row.insert(0, 'Cluster ID')
            writer.writerow(heading_row)
            for row in reader:
                cluster_id = cluster_membership[filename + str(row_id)]
                row.insert(0, fileno)
                row.insert(0, cluster_id)
                writer.writerow(row)
                row_id += 1