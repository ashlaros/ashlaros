/** A fake R2 bucket over a fixed key list, and a request builder. */

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
      const object = { body: 'bytes', size, writeHttpMetadata: () => {}, httpEtag: etag };
      if (match) {
        const offset = Number(match[1]);
        const end = match[2] === '' ? size - 1 : Number(match[2]);
        object.range = { offset, length: end - offset + 1 };
      }
      return object;
    },
  };
}

export const get = (host, path) => new Request(`https://${host}/${path}`);
