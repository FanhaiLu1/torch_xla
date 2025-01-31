import collections
import contextlib
import functools
from typing import Any, Callable, List, Optional, Tuple

import torch
import torch.distributed as dist
import torch_xla
import torch_xla.core.xla_model as xm
import torch_xla.core.xla_env_vars as xenv
import torch_xla.distributed.xla_multiprocessing as xmp
import torch_xla.runtime as xr
import torch_xla.utils.utils as xu


def device(index: int = None) -> torch.device:
  """Returns a given instance of an XLA device.

  If SPMD enables, returns a virtual device that wraps all devices available
  to this process.

  Args:
    index: index of the XLA device to be returned. Corresponds to index in
      `torch_xla.devices()`.

  Returns:
    An XLA `torch.device`.
  """

  return xm.xla_device(index)


def devices() -> List[torch.device]:
  """Returns all devices available in the current process.

  Returns:
    A list of XLA `torch.devices`.
  """

  return [torch.device(d) for d in xm.get_xla_supported_devices()]


def real_devices() -> List[str]:
  """Returns local XLA device types and indices.

  Returns:
    A list strings representing the XLA devices available in the current
    process, e.g. `['TPU:0', 'TPU:1', ...]`.
  """

  return torch_xla._XLAC._xla_real_devices()


def device_count() -> int:
  """Returns number of addressable devices in the current process."""
  return len(real_devices())


def sync():
  """Launches all pending graph operations."""
  xm.mark_step()


def step():
  """Wraps code that should be dispatched to the runtime.

  Experimental: `xla.step` is still a work in progress. Some code that currently
  works with `xla.step` but does not follow best practices will become errors in
  future releases. See https://github.com/pytorch/xla/issues/6751 for context.
  """
  return compile()


def compile(f: Optional[Callable] = None):
  """
  Optimizes given model/function using torch_xla's LazyTensor tracing mode.
  PyTorch/XLA will trace the given function with given inputs and then generate
  graphs to represent the pytorch operations happens within this function. This
  graph will be compiled by the XLA and executed on the accelerator(decided by the
  tensor's device). Eager mode will be disabled for the compiled region of the funciton.

  Args:
      model (Callable): Module/function to optimize, if not passed this function will
        act as a context manager.

  Example::

      # usage 1
      @torch_xla.compile()
      def foo(x):
        return torch.sin(x) + torch.cos(x)

      def foo2(x):
        return torch.sin(x) + torch.cos(x)
      # usage 2
      compiled_foo2 = torch_xla.compile(foo2)

      # usage 3
      with torch_xla.compile():
        res = foo2(x)
  """

  @contextlib.contextmanager
  def _step():
    saved_eager_mode_status = torch_xla._XLAC._get_use_eager_mode()
    torch_xla._XLAC._set_use_eager_mode(False)
    # Clear pending operations
    sync()

    try:
      yield
    finally:
      sync()
      torch_xla._XLAC._set_use_eager_mode(saved_eager_mode_status)

  return _step() if not f else _step()(f)


def manual_seed(seed, device=None):
  """Set the seed for generating random numbers for the current XLA device.

  Args:
    seed (integer): The state to be set.
    device (torch.device, optional): The device where the RNG state needs to be set.
      If missing the default device seed will be set.
  """
  xm.set_rng_state(seed, device)


# TODO(wcromar): Update args to type ParamSpec.
def launch(
    fn: Callable,
    args: Tuple = (),
    start_method: str = 'spawn',
    debug_single_process: bool = False,
):
  """ Entry to launch multiprocess.

  Raises:
    NotImplementedError: SPMD is not supported yet.
  """
  if xr.is_spmd():
    # TODO(piz): SPMD is specified differently from mp. Skip for now.
    raise NotImplementedError(
        'launch function does not support SPMD at this time')

  nprocs = 1 if debug_single_process else None

  if dist.is_torchelastic_launched():
    fn(xu.getenv_as(xenv.LOCAL_RANK, int), *args)
  else:
    xmp.spawn(fn, args=args, nprocs=nprocs, start_method=start_method)
