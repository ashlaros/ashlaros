"""Just enough of TFLite to run the gesture embedder and classifier.

OpenCV runs the two image networks, but not these two: the embedder opens
with a GATHER, which OpenCV 5.0's importer does not implement. Both are a
handful of dense layers over 63 numbers, so this reads the flatbuffer and
evaluates their operators in numpy rather than shipping a second runtime
for 128-wide matrix products. An operator outside the list is refused at
load time, not met halfway through a frame.
"""

import struct

import numpy as np

# builtin operator codes, from the TFLite schema
ADD = 0
FULLY_CONNECTED = 9
MUL = 18
RESHAPE = 22
SOFTMAX = 25
GATHER = 36
MEAN = 40
SUB = 41
DIV = 42
STRIDED_SLICE = 45
MAXIMUM = 55
REDUCE_MAX = 82
UNPACK = 88
REDUCE_MIN = 89

DTYPES = {0: np.float32, 2: np.int32, 4: np.int64}


class _Table:
    """A flatbuffer table: fields located through its vtable."""

    def __init__(self, buf: bytes, pos: int):
        self.buf = buf
        self.pos = pos
        self.vtable = pos - struct.unpack_from("<i", buf, pos)[0]
        self.vtable_len = struct.unpack_from("<H", buf, self.vtable)[0]

    def _offset(self, field: int) -> int:
        at = 4 + 2 * field
        if at >= self.vtable_len:
            return 0
        return struct.unpack_from("<H", self.buf, self.vtable + at)[0]

    def scalar(self, field: int, fmt: str, default=0):
        offset = self._offset(field)
        return struct.unpack_from("<" + fmt, self.buf, self.pos + offset)[0] if offset else default

    def _target(self, field: int) -> int | None:
        offset = self._offset(field)
        if not offset:
            return None
        at = self.pos + offset
        return at + struct.unpack_from("<I", self.buf, at)[0]

    def table(self, field: int) -> "_Table | None":
        at = self._target(field)
        return None if at is None else _Table(self.buf, at)

    def vector(self, field: int, dtype) -> np.ndarray:
        at = self._target(field)
        if at is None:
            return np.empty(0, dtype)
        count = struct.unpack_from("<I", self.buf, at)[0]
        return np.frombuffer(self.buf, dtype, count, at + 4)

    def tables(self, field: int) -> list["_Table"]:
        at = self._target(field)
        if at is None:
            return []
        count = struct.unpack_from("<I", self.buf, at)[0]
        items = (at + 4 + 4 * i for i in range(count))
        return [_Table(self.buf, i + struct.unpack_from("<I", self.buf, i)[0]) for i in items]


def _activate(x: np.ndarray, options: _Table | None) -> np.ndarray:
    # fused_activation_function is field 0 of every options table that has one
    code = options.scalar(0, "b") if options else 0
    if code == 0:
        return x
    if code == 1:
        return np.maximum(x, 0)
    if code == 3:
        return np.clip(x, 0, 6)
    raise ValueError(f"unsupported fused activation {code}")


def _reduce(fn):
    def run(args, options):
        x, axis = args[0], args[1]
        keep = bool(options.scalar(0, "B")) if options else False
        return fn(x, axis=tuple(int(a) for a in np.atleast_1d(axis)), keepdims=keep)

    return run


def _strided_slice(args, options):
    x, begin, end, strides = args
    if options.scalar(2, "i") or options.scalar(3, "i"):
        raise ValueError("ellipsis and new-axis masks are not supported")
    begin_mask, end_mask, shrink = (options.scalar(i, "i") for i in (0, 1, 4))
    index = []
    for d in range(len(begin)):
        if shrink >> d & 1:
            index.append(int(begin[d]))
            continue
        start = None if begin_mask >> d & 1 else int(begin[d])
        stop = None if end_mask >> d & 1 else int(end[d])
        index.append(slice(start, stop, int(strides[d])))
    return x[tuple(index)]


def _softmax(args, options):
    beta = options.scalar(0, "f", 1.0) if options else 1.0
    e = np.exp(beta * (args[0] - args[0].max(axis=-1, keepdims=True)))
    return e / e.sum(axis=-1, keepdims=True)


def _fully_connected(args, options):
    x, weights, bias = args
    y = x.reshape(-1, weights.shape[1]) @ weights.T
    if bias is not None:
        y = y + bias
    return _activate(y, options)


def _binary(fn):
    return lambda args, options: _activate(fn(args[0], args[1]), options)


OPERATORS = {
    ADD: _binary(np.add),
    SUB: _binary(np.subtract),
    MUL: _binary(np.multiply),
    DIV: _binary(np.divide),
    MAXIMUM: lambda args, options: np.maximum(args[0], args[1]),
    FULLY_CONNECTED: _fully_connected,
    SOFTMAX: _softmax,
    RESHAPE: lambda args, options: args[0].reshape([int(d) for d in args[1]]),
    GATHER: lambda args, options: np.take(args[0], args[1], axis=options.scalar(0, "i")),
    MEAN: _reduce(np.mean),
    REDUCE_MAX: _reduce(np.max),
    REDUCE_MIN: _reduce(np.min),
    STRIDED_SLICE: _strided_slice,
    # num and axis are fields 0 and 1 of UnpackOptions
    UNPACK: lambda args, options: [
        np.take(args[0], i, axis=options.scalar(1, "i")) for i in range(options.scalar(0, "i"))
    ],
}


class Model:
    """One float32 TFLite subgraph, evaluated operator by operator."""

    def __init__(self, data: bytes):
        root = _Table(data, struct.unpack_from("<I", data, 0)[0])
        # the deprecated int8 code saturates at 127, which is why the schema
        # added a second field; the larger of the two is the real one
        codes = [max(c.scalar(0, "b"), c.scalar(3, "i")) for c in root.tables(1)]
        buffers = root.tables(4)
        graph = root.tables(2)[0]

        self.constants: dict[int, np.ndarray] = {}
        for i, tensor in enumerate(graph.tables(0)):
            raw = buffers[tensor.scalar(2, "I")].vector(0, np.uint8)
            if raw.size:
                dtype = DTYPES[tensor.scalar(1, "b")]
                shape = [int(d) for d in tensor.vector(0, np.int32)]
                self.constants[i] = raw.view(dtype).reshape(shape)

        self.inputs = [int(i) for i in graph.vector(1, np.int32)]
        self.outputs = [int(i) for i in graph.vector(2, np.int32)]
        self.operators = []
        for op in graph.tables(3):
            code = codes[op.scalar(0, "I")]
            if code not in OPERATORS:
                raise ValueError(f"unsupported TFLite operator {code}")
            ins = [int(i) for i in op.vector(1, np.int32)]
            outs = [int(i) for i in op.vector(2, np.int32)]
            self.operators.append((OPERATORS[code], ins, outs, op.table(4)))

    def __call__(self, *inputs: np.ndarray) -> list[np.ndarray]:
        values = dict(self.constants)
        values.update(zip(self.inputs, inputs, strict=True))
        for run, ins, outs, options in self.operators:
            result = run([values[i] if i >= 0 else None for i in ins], options)
            if len(outs) == 1:
                result = [result]
            for i, value in zip(outs, result, strict=True):
                values[i] = np.asarray(value, np.float32)
        return [values[i] for i in self.outputs]
