from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import time

import torch
from torch.autograd import Variable
import torch.backends.cudnn as cudnn
import torch.nn as nn

import util


class TorchRunner(util.Runner):
    '''Runner for Torch models.'''

    def __init__(self, config, ModelClass, args=None, verbose=True):
        super(TorchRunner, self).__init__(config)
        cudnn.benchmark = True
        self.best_loss = float('inf')
        if args is None:
            args = [config, self.vocab, self.reader.label_space_size()]
        self.model = ModelClass(*args)
        self.initialize_model(self.model)
        self.criterion = nn.BCELoss()
        self.optimizer = util.torch_optimizer(config.optimizer, config.learning_rate,
                                              self.model.parameters())
        self.global_step = 0
        if config.load_file:
            if verbose:
                print('Loading model from', config.load_file, '...')
            model_state_dict, optim_state_dict, self.global_step, optim_name = \
                                                                        torch.load(config.load_file)
            self.model.load_state_dict(model_state_dict)
            if config.optimizer == optim_name:
                self.optimizer.load_state_dict(optim_state_dict)
            else:
                print('warning: saved model has a different optimizer, not loading optimizer.')
            if verbose:
                print('Loaded.')

    def initialize_model(self, model):
        model.cuda()
        model.embedding.cpu()  # don't waste GPU memory on embeddings

    def run_session(self, notes, lengths, labels, train=True):
        n_words = lengths.sum()
        start = time.time()
        notes = torch.from_numpy(notes).long()
        if train:
            self.model.zero_grad()
            notes = Variable(notes)
        else:
            notes = Variable(notes, volatile=True)
        probs = self.model(notes, lengths)
        loss = self.criterion(probs, Variable(torch.from_numpy(labels).float().cuda()))
        if train:
            loss.backward()
            self.optimizer.step()
            self.global_step += 1
        probs = probs.data.cpu().numpy()
        loss = loss.data.cpu().numpy()
        p, r, f = util.f1_score(probs, labels, 0.5)
        ap = util.average_precision(probs, labels)
        p8 = util.precision_at_k(probs, labels, 8)
        end = time.time()
        wps = n_words / (end - start)
        return ([loss, p, r, f, ap, p8, wps], [])

    def best_val_loss(self, loss):
        '''Compare loss with the best validation loss, and return True if a new best is found'''
        if loss[0] <= self.best_loss:
            self.best_loss = loss[0]
            return True
        else:
            return False

    def save_model(self, save_file, verbose=True):
        if save_file:
            if not self.config.save_overwrite:
                save_file += '.' + int(self.global_step)
            if verbose:
                print('Saving model to', save_file, '...')
            with open(save_file, 'wb') as f:
                states = [self.model.state_dict(), self.optimizer.state_dict(), self.global_step,
                          self.config.optimizer]
                torch.save(states, f)
            if verbose:
                print('Saved.')

    def loss_str(self, losses):
        loss, p, r, f, ap, p8, wps = losses
        return "Loss: %.4f, Precision: %.4f, Recall: %.4f, F-score: %.4f, AvgPrecision: %.4f, " \
               "Precision@8: %.4f, WPS: %.2f" % (loss, p, r, f, ap, p8, wps)

    def output(self, step, losses, extra, train=True):
        print("GS:%d, S:%d.  %s" % (self.global_step, step, self.loss_str(losses)))