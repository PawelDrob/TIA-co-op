"""The tests of the HMI preview. A server they start keeps its record of hmipreview\running.py in a folder of their own,
not where the TIA dashboard of this machine looks."""
import atexit
import os
import shutil
import tempfile

os.environ['HMIPREVIEW_RUNNING'] = tempfile.mkdtemp(prefix='hmipreview-running-')
atexit.register(shutil.rmtree, os.environ['HMIPREVIEW_RUNNING'], True)
