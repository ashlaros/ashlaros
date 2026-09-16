/** A fake R2 bucket over a fixed key list, and a request builder. */

// What a latest/ pointer holds: the version the alias points at, taken
// from the newest version prefix in the fake bucket so a test does not
// have to state it twice.
// Only the two alias keys are pointers. latest/ also holds screenshots and
// the tour video, which are real files: sizing those like a version string
// broke the media test, which is exactly the distinction that matters.
const isPointer = (key) =>
  key === 'latest/ashlaros.iso' || key === 'latest/ashlaros-rpi5.img.xz';
const aliasBody = (key) => (isPointer(key) ? '2026.09.10' : 'bytes');

export function bucketOf(keys, { etag = '"e"', pageSize = 1000 } = {}) {
  return {
    // Paginated like R2: a page is capped and says so, and the caller is
    // expected to follow the cursor. A fake that returned everything
    // could not tell a paginating reader from one that silently drops
    // whatever falls past the first page.
    list: async ({ prefix = '', delimiter, cursor } = {}) => {
      const under = keys.filter((k) => k.startsWith(prefix));
      const dirs = new Set();
      const objects = [];
      for (const k of under) {
        const rest = k.slice(prefix.length);
        const cut = delimiter ? rest.indexOf(delimiter) : -1;
        if (cut >= 0) dirs.add(prefix + rest.slice(0, cut + 1));
        else objects.push({ key: k, size: 2_000_000_000, uploaded: new Date(0) });
      }
      const start = cursor ? Number(cursor) : 0;
      const page = objects.slice(start, start + pageSize);
      const truncated = start + pageSize < objects.length;
      return {
        objects: page,
        delimitedPrefixes: [...dirs],
        truncated,
        cursor: truncated ? String(start + pageSize) : undefined,
      };
    },

    head: async (k) => (keys.includes(k) ? { httpEtag: etag, size: 334_986 } : null),
    // size and range are what R2 really returns, and what the video
    // element needs: without them the response carries no content-length
    get: async (k, options = {}) => {
      if (!keys.includes(k)) return null;
      const size = 334_986;
      const header = options.range?.get?.('range');
      const match = header?.match(/^bytes=(\d+)-(\d*)$/);
      // text() because latest/ now holds a version string the worker
      // reads rather than an image it streams; R2 objects carry it and a
      // fake without it cannot exercise the redirect at all
      // A pointer is a version string and an image is gigabytes, and the
      // handler now refuses to read a body too large to be a pointer -
      // so the fake has to tell them apart the way R2 does, by size.
      const body = aliasBody(k);
      const object = {
        body: 'bytes',
        size: isPointer(k) ? body.length : size,
        writeHttpMetadata: () => {},
        httpEtag: etag,
        text: async () => body,
      };
      if (match) {
        const offset = Number(match[1]);
        const end = match[2] === '' ? size - 1 : Number(match[2]);
        object.range = { offset, length: end - offset + 1 };
      } else {
        // R2 reports a range for a full read as well - offset 0, the whole
        // length - and a stub that left it undefined could not see the bug
        // where every plain GET was answered 206.
        object.range = { offset: 0, length: size };
      }
      return object;
    },
  };
}

// Everything is one hostname now, and a site is a path prefix. The first
// argument stayed a site name rather than becoming a literal prefix so the
// call sites still read as "this request is for the ISO site" - and so a
// test cannot accidentally ask the docs binding for a bucket object.
const PREFIXES = {
  'iso.ashlaros.download': 'iso/',
  'packages.ashlaros.download': 'packages/',
  'ashlaros.download': '',
};

export const get = (site, path) => {
  const prefix = PREFIXES[site];
  if (prefix === undefined) throw new Error(`unknown site ${site}`);
  return new Request(`https://ashlaros.download/${prefix}${path}`);
};
