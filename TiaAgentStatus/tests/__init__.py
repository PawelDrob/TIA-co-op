"""The tests of the agent status tools. The TIA dashboard they run reads the records of running HMI previews from a
folder of their own, not the one the previews of this machine write (TiaHmiGenerator\hmipreview\running.py)."""
import atexit
import os
import shutil
import tempfile

os.environ['HMIPREVIEW_RUNNING'] = tempfile.mkdtemp(prefix='agent-status-previews-')
atexit.register(shutil.rmtree, os.environ['HMIPREVIEW_RUNNING'], True)
