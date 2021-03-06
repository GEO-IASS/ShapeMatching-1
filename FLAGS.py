# Number of images to process in a batch.
batch_size = 128
# Path to the data directory.
data_dir = "/home/bfb/Affinity/ShapeMatching/Dataset/Rotation"
# Train the model using fp16.
use_fp16 = False

# Directory where to write event logs.
train_dir = './MSHAPES_train'
# Number of batches to run.
max_steps = 50000 #1000000
# Whether to log device placement.
log_device_placement = False
# How often to log results to the console.
log_frequency = 100

# Global constants describing the MSHAPES data set.
IMAGE_SIZE = 100
NUM_CLASSES = 2
NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN = 100000
NUM_EXAMPLES_PER_EPOCH_FOR_EVAL = 20000

# Constants describing the training process.
MOVING_AVERAGE_DECAY = 0.9999     # The decay to use for the moving average.
NUM_EPOCHS_PER_DECAY = 5.0      # Epochs after which learning rate decays.
LEARNING_RATE_DECAY_FACTOR = 0.5  # Learning rate decay factor.
INITIAL_LEARNING_RATE = 0.001       # Initial learning rate.

# If a model is trained with multiple GPUs, prefix all Op names with tower_name
# to differentiate the operations. Note that this prefix is removed from the
# names of the summaries when visualizing a model.
TOWER_NAME = 'tower'

# Where to download the MSHAPES dataset from
DATA_URL = 'https://electronneutrino.com/affinity/shapes/datasets/MSHAPES_180DEG_ONECOLOR_SIMPLE_50k_100x100.zip'

NOTIFICATION_EMAIL = 'qc_zhao@outlook.com'

CHECK_DATASET = True

RESTORE = False
RESTORE_FROM = 'summaries/netstate/saved_state-3000'

# The version of model to use.
#   0: CIFAR-10 model
#   1: preprocess input images respectively
#   2: preprocess input images respectively with rotation invariance
model_version = 2

# Architecture parameters
CONVOLUTIONAL_LAYER_DEPTH = 16
KEEP_PROB = 0.5
