"""
st5.py

This file contains the graph structure for simpletrain5.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import re

import tensorflow as tf
import numpy as np

import FLAGS
import sm_input


# Global constants describing the MSHAPES data set.
IMAGE_SIZE = FLAGS.IMAGE_SIZE
NUM_CLASSES = FLAGS.NUM_CLASSES
NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN = FLAGS.NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN
NUM_EXAMPLES_PER_EPOCH_FOR_EVAL = FLAGS.NUM_EXAMPLES_PER_EPOCH_FOR_EVAL
TOWER_NAME = FLAGS.TOWER_NAME

# Constants describing the training process.
MOVING_AVERAGE_DECAY = FLAGS.MOVING_AVERAGE_DECAY  # The decay to use for the moving average.
NUM_EPOCHS_PER_DECAY = FLAGS.NUM_EPOCHS_PER_DECAY  # Epochs after which learning rate decays.
LEARNING_RATE_DECAY_FACTOR = FLAGS.LEARNING_RATE_DECAY_FACTOR  # Learning rate decay factor.
INITIAL_LEARNING_RATE = FLAGS.INITIAL_LEARNING_RATE  # Initial learning rate.


def inputs(eval_data):
    """Construct input for MSHAPES evaluation using the Reader ops.
    Args:
      eval_data: bool, indicating if one should use the train or eval data set.
    Returns:
      images: Images. 4D tensor of [batch_size, IMAGE_SIZE, IMAGE_SIZE, 6] size.
      labels: Labels. 1D tensor of [batch_size] size.
    Raises:
      ValueError: If no data_dir
    """
    with tf.variable_scope('READ'):
        if not FLAGS.data_dir:
            raise ValueError('Please supply a data_dir')
        data_dir = os.path.join(FLAGS.data_dir, '')
        images, labels = sm_input.inputs(eval_data=eval_data,
                                         data_dir=data_dir,
                                         batch_size=FLAGS.batch_size)

        if FLAGS.use_fp16:
            images = tf.cast(images, tf.float16)
            labels = tf.cast(labels, tf.float16)

        return images, labels


def rotation_invariant_net(name, images):
    """
    A convolutional neural network which maintain the rotation invariance of the input image.
    Reference: "Learning rotation invariant convolutional filters for texture classification" by Diego Marcos, etc
        https://arxiv.org/pdf/1604.06720.pdf
    :param name: the name of network
    :param images: input tensor with shape as [batch_size, 100, 100, 3]
    :return: rotation invariant features
    """

    ROTATION_GROUP_NUMBER = 8
    DISCRETE_ORIENTATION_NUMBER = 16
    filter_size = 27

    with tf.variable_scope(name):
        # a common convolution operation
        with tf.variable_scope('canonical_conv') as scope:
            kernel = _variable_with_weight_decay('weights',
                                                 shape=[filter_size, filter_size, 3, ROTATION_GROUP_NUMBER],  # the size of the kernel is larger than those are typically used
                                                 stddev=5e-3,
                                                 wd=0.0)
            conv = tf.nn.conv2d(images, kernel, [1, 1, 1, 1], padding='VALID')
            biases = _variable_on_cpu('biases', [ROTATION_GROUP_NUMBER], tf.constant_initializer(1e-2))
            canonical_conv = tf.nn.bias_add(conv, biases)

        # rotate each channel for DISCRETE_ORIENTATION_NUMBER times and form ROTATION_GROUP_NUMBER groups
        with tf.variable_scope('oriented_max_pool') as scope:

            groups = []
            ROTATE_ANGLE = 2 * np.pi / float(DISCRETE_ORIENTATION_NUMBER)
            for m in xrange(ROTATION_GROUP_NUMBER):
                group_canonical = canonical_conv[:, :, :, m:m + 1]
                rotations = []
                for r in xrange(DISCRETE_ORIENTATION_NUMBER):
                    rot = tf.contrib.image.rotate(group_canonical,
                                                  r * ROTATE_ANGLE,
                                                  'BILINEAR')
                    rotations.append(rot)
                concat_rotations = tf.concat(rotations, axis=3)
                rotation_reduce_max = tf.reduce_max(concat_rotations, axis=3, keep_dims=True)
                groups.append(rotation_reduce_max)
            # shape: [batch_size, width, height, ROTATION_GROUP_NUMBER]
            oriented_max_pool = tf.concat(groups, axis=3)

        with tf.variable_scope('spatial_max_pool') as scope:
            spatial_max_pool = tf.nn.max_pool(oriented_max_pool,
                                              ksize=[1,2,2,1],
                                              strides=[1,2,2,1],
                                              padding='SAME')

        activated = tf.nn.relu(spatial_max_pool)
        return activated


def input_process(name, images):
    """
    Model to extract features from one of the input image. Two layers of convolution and pool
    :param name: name of the input
    :param input_image: tensor_shape = [batch_size, width, height, 3]
    :return: feature logits
    """
    CONV1_DEPTH = FLAGS.CONVOLUTIONAL_LAYER_DEPTH
    CONV2_DEPTH = FLAGS.CONVOLUTIONAL_LAYER_DEPTH

    channel_num = images.get_shape().as_list()[3]
    # conv1
    with tf.variable_scope(name):
        with tf.variable_scope('conv') as scope:
            kernel = _variable_with_weight_decay('weights',
                                                 shape=[5, 5, channel_num, CONV1_DEPTH],
                                                 stddev=5e-3,
                                                 wd=0.0)
            conv = tf.nn.conv2d(images, kernel, [1, 1, 1, 1], padding='SAME')
            biases = _variable_on_cpu('biases', [CONV1_DEPTH], tf.constant_initializer(1e-2))
            pre_activation = tf.nn.bias_add(conv, biases)
            conv1 = tf.nn.relu(pre_activation, name=scope.name)
            _activation_summary(conv1)

            # pool1
            pool1 = tf.nn.max_pool(conv1, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1],
                                   padding='SAME', name='pool')
            # norm1
            norm1 = tf.nn.lrn(pool1, 4, bias=1.0, alpha=0.001 / 9.0, beta=0.75,
                              name='norm')

        # conv2
        with tf.variable_scope('conv2') as scope:
            kernel = _variable_with_weight_decay('weights',
                                                 shape=[5, 5, CONV1_DEPTH, CONV2_DEPTH],
                                                 stddev=5e-2,
                                                 wd=0.0)
            conv = tf.nn.conv2d(norm1, kernel, [1, 1, 1, 1], padding='SAME')
            biases = _variable_on_cpu('biases', [CONV2_DEPTH], tf.constant_initializer(0.1))
            pre_activation = tf.nn.bias_add(conv, biases)
            conv2 = tf.nn.relu(pre_activation, name=scope.name)
            _activation_summary(conv2)

            # norm2
            norm2 = tf.nn.lrn(conv2, 4, bias=1.0, alpha=0.001 / 9.0, beta=0.75,
                              name='norm1')
            # pool2
            pool2 = tf.nn.max_pool(norm2, ksize=[1, 3, 3, 1],
                                   strides=[1, 2, 2, 1], padding='SAME', name='pool1')

    return pool2


def input_process_with_rotation(name, images):
    rotation_invariant = rotation_invariant_net(name, images)
    return input_process(name, rotation_invariant)


# Full connection layer
def full_connection_layer(features, eval=False):
    FC1_NUM = 384
    FC2_NUM = 192
    # FC1
    with tf.variable_scope('FC1') as scope:
        # Move everything into depth so we can perform a single matrix multiply.
        reshape = tf.reshape(features, [FLAGS.batch_size, -1])
        dim = reshape.get_shape()[1].value
        weights = _variable_with_weight_decay('weights', shape=[dim, FC1_NUM],
                                              stddev=0.04, wd=0.004)
        biases = _variable_on_cpu('biases', [FC1_NUM], tf.constant_initializer(0.1))
        fc1 = tf.nn.relu(tf.matmul(reshape, weights) + biases, name=scope.name)
        _activation_summary(fc1)
        keep_prob = FLAGS.KEEP_PROB if eval else 1.0
        fc1_dropout = tf.nn.dropout(fc1, keep_prob=keep_prob)

    # FC2
    with tf.variable_scope('FC2') as scope:
        weights = _variable_with_weight_decay('weights', shape=[FC1_NUM, FC2_NUM],  # 192
                                              stddev=0.04, wd=0.004)
        biases = _variable_on_cpu('biases', [FC2_NUM], tf.constant_initializer(0.1))
        fc2 = tf.nn.relu(tf.matmul(fc1_dropout, weights) + biases, name=scope.name)
        _activation_summary(fc2)

    # linear layer(WX + b),
    # We don't apply softmax here because
    # tf.nn.sparse_softmax_cross_entropy_with_logits accepts the unscaled logits
    # and performs the softmax internally for efficiency.
    with tf.variable_scope('softmax_linear') as scope:
        weights = _variable_with_weight_decay('weights', [FC2_NUM, NUM_CLASSES],
                                              stddev=1 / float(FC2_NUM), wd=0.0)
        biases = _variable_on_cpu('biases', [NUM_CLASSES],
                                  tf.constant_initializer(0.0))
        softmax_linear = tf.add(tf.matmul(fc2, weights), biases, name=scope.name)
        _activation_summary(softmax_linear)

    return softmax_linear


def inference(images, eval=False):
    """
    Build the model in which firstly extract features from both input images first. Then concat them together

    :param images: Images reterned from distored_inputs() or inputs(), tensor_shape = [batch_size, width, height, 6]
    :return: Logits
    """

    inference_model = {
        0: inference_v0,
        1: inference_v1,
        2: inference_v2,
        3: inference_v3
    }

    return inference_model[FLAGS.model_version](images, eval)


def inference_v3(images, eval=False):
    """
    Version 3, cross product two input images

    :param images: returned from inputs(). shape=[batch_size, IMAGE_SIZE, IMAGE_SIZE, 6]
    :param eval: if evaluate
    :return: logits
    """
    with tf.variable_scope('cross_prod') as scope:
        cross_prod = tf.cross(images[:,:,:,:3], images[:,:,:,3:])
    return inference_v0(cross_prod, eval)


def inference_v2(images, eval=False):
    """
    Version 2, preprocess two input images with rotation variance respectively.

    :param images: returned from inputs(). shape=[batch_size, IMAGE_SIZE, IMAGE_SIZE, 6]
    :param eval: if evaluate
    :return: logits
    """
    with tf.variable_scope('input') as scope:
        input_feature_L = input_process_with_rotation('input_L', images[:,:,:,:3])
        input_feature_K = input_process_with_rotation('input_K', images[:,:,:,3:])
        sh = images.get_shape().as_list()
        input_concat = tf.concat([input_feature_L, input_feature_K], axis=len(sh)-1)

    return full_connection_layer(input_concat, eval)


def inference_v1(images, eval=False):
    """
    Version 1, preprocess two input images respectively.

    :param images: returned from inputs(). shape=[batch_size, IMAGE_SIZE, IMAGE_SIZE, 6]
    :param eval: if evaluate
    :return: logits
    """
    with tf.variable_scope('input') as scope:
        input_feature_L = input_process('input_L', images[:,:,:,:3])
        input_feature_K = input_process('input_K', images[:,:,:,3:])
        sh = images.get_shape().as_list()
        input_concat = tf.concat([input_feature_L, input_feature_K], axis=len(sh)-1)

    return full_connection_layer(input_concat, eval)


def inference_v0(images, eval=False):
    """
    Version 0, CIFAR-10 model.

    :param images: returned from inputs(). shape=[batch_size, IMAGE_SIZE, IMAGE_SIZE, 6]
    :param eval: if evaluate
    :return: logits
    """

    CONV1_DEPTH = 64
    CONV2_DEPTH = 64
    channel_num = images.get_shape().as_list()[3]

    # conv1
    with tf.variable_scope('conv1') as scope:
        kernel = _variable_with_weight_decay('weights',
                                             shape=[5, 5, channel_num, CONV1_DEPTH],
                                             stddev=5e-3,
                                             wd=0.0)
        conv = tf.nn.conv2d(images, kernel, [1, 1, 1, 1], padding='SAME')
        biases = _variable_on_cpu('biases', [CONV1_DEPTH], tf.constant_initializer(1e-2))
        pre_activation = tf.nn.bias_add(conv, biases)
        conv1 = tf.nn.relu(pre_activation, name=scope.name)
        _activation_summary(conv1)

        # pool1
        pool1 = tf.nn.max_pool(conv1, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1],
                               padding='SAME', name='pool1')
        # norm1
        norm1 = tf.nn.lrn(pool1, 4, bias=1.0, alpha=0.001 / 9.0, beta=0.75,
                          name='norm1')

    # conv2
    with tf.variable_scope('conv2') as scope:
        kernel = _variable_with_weight_decay('weights',
                                             shape=[5, 5, CONV1_DEPTH, CONV2_DEPTH],
                                             stddev=5e-2,
                                             wd=0.0)
        conv = tf.nn.conv2d(norm1, kernel, [1, 1, 1, 1], padding='SAME')
        biases = _variable_on_cpu('biases', [CONV2_DEPTH], tf.constant_initializer(0.1))
        pre_activation = tf.nn.bias_add(conv, biases)
        conv2 = tf.nn.relu(pre_activation, name=scope.name)
        _activation_summary(conv2)

        # norm2
        norm2 = tf.nn.lrn(conv2, 4, bias=1.0, alpha=0.001 / 9.0, beta=0.75,
                          name='norm2')
        # pool2
        pool2 = tf.nn.max_pool(norm2, ksize=[1, 3, 3, 1],
                               strides=[1, 2, 2, 1], padding='SAME', name='pool2')

    return full_connection_layer(pool2, eval)



def loss(logits, labels):
    """Calculates the cross-entropy loss.
    Args:
      logits: Logits from inference().
      labels: Labels from inputs(). 1-D tensor
              of shape [batch_size]
    Returns:
      Loss tensor of type float.
    """
    # Calculate the average cross entropy loss across the batch.
    labels = tf.cast(labels, tf.int64)
    cross_entropy = tf.nn.sparse_softmax_cross_entropy_with_logits(
        labels=labels, logits=logits, name='cross_entropy_per_example')
    cross_entropy_mean = tf.reduce_mean(cross_entropy, name='cross_entropy')
    tf.add_to_collection('losses', cross_entropy_mean)

    # The total loss is defined as the cross entropy loss plus all of the weight
    # decay terms (L2 loss).
    # return tf.add_n(tf.get_collection('losses'), name='total_loss')

    return cross_entropy_mean + 6 - 6



def train(total_loss, global_step):
    """
    Train MSHAPES model.
    Create an optimizer and apply to all trainable variables. Add moving
    average for all trainable variables.

    :param total_loss: Total loss from loss().
    :param global_step: Integer Variable counting the number of training steps processed.
    :return: op for training.
    """
    # Variables that affect learning rate.
    with tf.variable_scope('train_op'):
        num_batches_per_epoch = NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN / FLAGS.batch_size
        decay_steps = int(num_batches_per_epoch * NUM_EPOCHS_PER_DECAY)

        # Decay the learning rate exponentially based on the number of steps.
        lr = tf.train.exponential_decay(INITIAL_LEARNING_RATE,
                                        global_step,
                                        decay_steps,
                                        LEARNING_RATE_DECAY_FACTOR,
                                        staircase=True)
        tf.summary.scalar('learning_rate', lr)

        # train_op = tf.train.AdamOptimizer(learning_rate=lr).minimize(total_loss)

        # Generate moving averages of all losses and associated summaries.
        loss_averages_op = _add_loss_summaries(total_loss)

        # Compute gradients.
        with tf.control_dependencies([loss_averages_op]):
            opt = tf.train.AdamOptimizer(learning_rate=lr)
            grads = opt.compute_gradients(total_loss)

        # Apply gradients.
        apply_gradient_op = opt.apply_gradients(grads, global_step=global_step)

        # Add histograms for trainable variables.
        for var in tf.trainable_variables():
            tf.summary.histogram(var.op.name, var)

        # Add histograms for gradients.
        for grad, var in grads:
            if grad is not None:
                tf.summary.histogram(var.op.name + '/gradients', grad)

        # Track the moving averages of all trainable variables.
        variable_averages = tf.train.ExponentialMovingAverage(
            MOVING_AVERAGE_DECAY, global_step)
        variables_averages_op = variable_averages.apply(tf.trainable_variables())

        with tf.control_dependencies([apply_gradient_op, variables_averages_op]):
            train_op = tf.no_op(name='train')

    return train_op


def _activation_summary(x):
    """Helper to create summaries for activations.
    Creates a summary that provides a histogram of activations.
    Creates a summary that measures the sparsity of activations.
    Args:
      x: Tensor
    Returns:
      nothing


    author: The TensorFlow Authors
    """
    # Remove 'tower_[0-9]/' from the name in case this is a multi-GPU training
    # session. This helps the clarity of presentation on tensorboard.
    tensor_name = re.sub('%s_[0-9]*/' % TOWER_NAME, '', x.op.name)
    tf.summary.histogram(tensor_name + '/activations', x)
    tf.summary.scalar(tensor_name + '/sparsity',
                      tf.nn.zero_fraction(x))



def _add_loss_summaries(total_loss):
    """Add summaries for losses in CIFAR-10 model.
    Generates moving average for all losses and associated summaries for
    visualizing the performance of the network.
    Args:
      total_loss: Total loss from loss().
    Returns:
      loss_averages_op: op for generating moving averages of losses.
    """
    # Compute the moving average of all individual losses and the total loss.
    loss_averages = tf.train.ExponentialMovingAverage(0.9, name='avg')
    losses = tf.get_collection('losses')
    loss_averages_op = loss_averages.apply(losses + [total_loss])

    # Attach a scalar summary to all individual losses and the total loss; do the
    # same for the averaged version of the losses.
    for l in losses + [total_loss]:
        # Name each loss as '(raw)' and name the moving average version of the loss
        # as the original loss name.
        tf.summary.scalar(l.op.name + ' (raw)', l)
        tf.summary.scalar(l.op.name, loss_averages.average(l))

    return loss_averages_op



def _variable_on_cpu(name, shape, initializer):
    """Helper to create a Variable stored on CPU memory.
    Args:
      name: name of the variable
      shape: list of ints
      initializer: initializer for Variable
    Returns:
      Variable Tensor
    """
    with tf.device('/cpu:0'):
        dtype = tf.float16 if FLAGS.use_fp16 else tf.float32
        var = tf.get_variable(name, shape, initializer=initializer, dtype=dtype)
    return var



def _variable_with_weight_decay(name, shape, stddev, wd):
    """Helper to create an initialized Variable with weight decay.
    Note that the Variable is initialized with a truncated normal distribution.
    A weight decay is added only if one is specified.
    Args:
      name: name of the variable
      shape: list of ints
      stddev: standard deviation of a truncated Gaussian
      wd: add L2Loss weight decay multiplied by this float. If None, weight
          decay is not added for this Variable.
    Returns:
      Variable Tensor
    """
    dtype = tf.float16 if FLAGS.use_fp16 else tf.float32
    var = _variable_on_cpu(
        name,
        shape,
        tf.truncated_normal_initializer(stddev=stddev, dtype=dtype))
    if wd is not None:
        weight_decay = tf.multiply(tf.nn.l2_loss(var), wd, name='weight_loss')
        tf.add_to_collection('losses', weight_decay)
    return var
