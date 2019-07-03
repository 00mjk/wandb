'''W&B Callback for fast.ai

This module hooks fast.ai Learners to Weights & Biases through a callback.
Requested logged data can be configured through the callback constructor.

Examples:
    WandbCallback can be used when initializing the Learner::

        from wandb.fastai import WandbCallback
        [...]
        learn = Learner(data, ..., callback_fns=WandbCallback)
        learn.fit(epochs)
    
    Custom parameters can be given using functools.partial::

        from wandb.fastai import WandbCallback
        from functools import partial
        [...]
        learn = Learner(data, ..., callback_fns=partial(WandbCallback, ...))
        learn.fit(epochs)

    Finally, it is possible to use WandbCallback only when starting
    training. In this case it must be instantiated::

        learn.fit(..., callbacks=WandbCallback())

    or, with custom parameters::

        learn.fit(..., callbacks=WandBCallback(learn, ...))
'''
import wandb
from fastai.callbacks import TrackerCallback
from pathlib import Path
import random


class WandbCallback(TrackerCallback):

    # Record if watch has been called previously (even in another instance)
    watch_called = False

    def __init__(self,
                 learn,
                 log=None,
                 save_model=False,
                 monitor='val_loss',
                 mode='auto',
                 data_type='images',
                 validation_data=None,
                 predictions=32):
        """WandB fast.ai Callback

        Automatically saves model topology, losses & metrics.
        Optionally logs weights, gradients, sample predictions and best trained model.

        Args:
            learn (fastai.basic_train.Learner): the fast.ai learner to hook.
            log (str): "gradients", "parameters", "all", or None. Losses & metrics are always logged.
            save_model (bool): save model at the end of each epoch.
            monitor (str): metric to monitor for saving best model.
            mode (str): "auto", "min" or "max" to compare "monitor" values and define best model.
            data_type (str): "images" or None. Used to display sample predictions.
            validation_data (list): data used for sample predictions if data_type is set.
            predictions (int): number of predictions to make if data_type is set and validation_data is None.
        """

        # Check if wandb.init has been called
        if wandb.run is None:
            raise ValueError(
                'You must call wandb.init() before WandbCallback()')

        # Adapted from fast.ai "SaveModelCallback"
        super().__init__(learn, monitor=monitor, mode=mode)
        self.save_model = save_model
        self.model_path = Path(wandb.run.dir) / 'bestmodel.pth'

        self.log = log
        self.data_type = data_type
        self.best = None

        # Select items for sample predictions to see evolution along training
        self.validation_data = validation_data
        if data_type and not self.validation_data:
            predictions = min(predictions, len(learn.data.valid_ds))
            indices = random.sample(range(len(learn.data.valid_ds)),
                                    predictions)
            self.validation_data = [learn.data.valid_ds[i] for i in indices]

    def on_train_begin(self, **kwargs):
        "Call watch method to log model topology, gradients & weights"

        # Set self.best, method inherited from "TrackerCallback" by "SaveModelCallback"
        super().on_train_begin()

        # Ensure we don't call "watch" multiple times
        if not WandbCallback.watch_called:
            WandbCallback.watch_called = True

            # Logs model topology and optionally gradients and weights
            wandb.watch(self.learn.model, log=self.log)

    def on_epoch_end(self, epoch, smooth_loss, last_metrics, **kwargs):
        "Logs training loss, validation loss and custom metrics & log prediction samples & save model"

        if self.save_model:
            # Adapted from fast.ai "SaveModelCallback"
            current = self.get_monitor_value()
            if current is not None and self.operator(current, self.best):
                print(
                    'Better model found at epoch {} with {} value: {}.'.format(
                        epoch, self.monitor, current))
                self.best = current

                # Save within wandb folder
                with self.model_path.open('wb') as model_file:
                    self.learn.save(model_file)

        # Log sample predictions
        if self.validation_data:
            pred_log = []

            for x, y in self.validation_data:
                pred = self.learn.predict(x)

                # scalar -> likely to be a category
                if not pred[1].shape:
                    pred_log.append(
                        wandb.Image(
                            x.data,
                            caption='Ground Truth: {}\nPrediction: {}'.format(
                                y, pred[0])))

            wandb.log({"Prediction Samples": pred_log}, commit=False)

        # Log losses & metrics
        # Adapted from fast.ai "CSVLogger"
        logs = {
            name: stat
            for name, stat in list(
                zip(self.learn.recorder.names, [epoch, smooth_loss] +
                    last_metrics))[1:]
        }
        wandb.log(logs)

    def on_train_end(self, **kwargs):
        "Load the best model."

        if self.save_model:
            # Adapted from fast.ai "SaveModelCallback"
            if self.model_path.is_file():
                with self.model_path.open('rb') as model_file:
                    self.learn.load(model_file, purge=False)
                    print('Loaded best saved model from {}'.format(
                        self.model_path))


# Functions imported from fastai.core


def func_args(func) -> bool:
    "Return the arguments of `func`."
    code = func.__code__
    return code.co_varnames[:code.co_argcount]


def has_arg(func, arg) -> bool:
    "Check if `func` accepts `arg`."
    return arg in func_args(func)


def split_kwargs_by_func(kwargs, func):
    "Split `kwargs` between those expected by `func` and the others."
    args = func_args(func)
    func_kwargs = {a: kwargs.pop(a) for a in args if a in kwargs}
    return func_kwargs, kwargs


def grab_idx(x, i, batch_first: bool = True):
    "Grab the `i`-th batch in `x`, `batch_first` stating the batch dimension."
    if batch_first:
        return ([o[i].cpu() for o in x] if is_listy(x) else x[i].cpu())
    else:
        return ([o[:, i].cpu() for o in x] if is_listy(x) else x[:, i].cpu())


def is_listy(x) -> bool:
    return isinstance(x, (tuple, list))
