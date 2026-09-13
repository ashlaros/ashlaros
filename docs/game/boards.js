/**
 * Rendering the three boards.
 *
 * Shared by both games because the shape is identical and the difference
 * is a query parameter. The worker already serves all three; only the
 * daily one was ever drawn.
 *
 * Why three rather than one: scores from different seeds are not
 * comparable, so a single table of best runs ranks the kindest seed
 * rather than the best play. Daily is the competition and resets. The
 * rolling window is recent form. All-time is one row per player, which
 * keeps it about people - still seed-luck-flattered, but it does not
 * pretend otherwise.
 */

const escape = (text) => String(text).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

const WINDOWS = {
  today: { label: 'Today', path: (game) => `/game/board?game=${game}` },
  '30d': { label: '30 days', path: (game) => `/game/all-time?game=${game}` },
  all: { label: 'All time', path: (game) => `/game/all-time?game=${game}&window=all` },
};

/**
 * Wire the board switcher.
 *
 * `onDaily` is handed the daily rows, because the page needs them to
 * decide whether a finished run placed - that question is about today
 * and only about today.
 */
export function createBoards({ game, tableEl, tabsEl, onDaily }) {
  let current = 'today';
  const cache = new Map();

  const buttons = Object.entries(WINDOWS).map(([key, { label }]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.dataset.window = key;
    button.addEventListener('click', () => show(key));
    tabsEl.append(button);
    return button;
  });

  function mark() {
    for (const button of buttons) {
      button.setAttribute('aria-current', String(button.dataset.window === current));
    }
  }

  function render(rows, key) {
    if (!rows.length) {
      tableEl.innerHTML =
        key === 'today'
          ? '<tr><td>No runs yet today.</td></tr>'
          : '<tr><td>Nothing here yet.</td></tr>';
      return;
    }
    tableEl.innerHTML = rows
      .map((row, i) => {
        // the run count only exists on the aggregate boards, and it is
        // what stops "one row per player" reading as "played once"
        const runs = key === 'today' || !row.runs ? '' : `<td>${Number(row.runs)}</td>`;
        return (
          `<tr><td>${i + 1}</td><td>${escape(row.player)}</td>` +
          `<td>${Number(row.score).toLocaleString('en-US')}</td>${runs}</tr>`
        );
      })
      .join('');
  }

  async function show(key) {
    current = key;
    mark();
    if (cache.has(key)) {
      render(cache.get(key), key);
      return;
    }
    try {
      const response = await fetch(WINDOWS[key].path(game));
      const data = await response.json();
      const rows = data.scores ?? [];
      cache.set(key, rows);
      if (key === 'today') onDaily?.(rows);
      render(rows, key);
    } catch {
      tableEl.innerHTML = '<tr><td>The board is unreachable.</td></tr>';
    }
  }

  /**
   * Today's rows, whichever tab is showing.
   *
   * The page needs them to decide whether a finished run placed, and that
   * question is about today - so they are fetched even when the visible
   * board is an aggregate one. Fetched and handed over without being
   * rendered, because rendering them would yank the tab out from under
   * whoever chose it.
   */
  async function refreshDaily() {
    try {
      const response = await fetch(WINDOWS.today.path(game));
      const rows = (await response.json()).scores ?? [];
      cache.set('today', rows);
      onDaily?.(rows);
    } catch {
      // the board being unreachable is already visible on screen; a run
      // that cannot check whether it placed simply offers to submit
    }
  }

  return {
    show,
    /** After a submission every board may have changed, including this one. */
    async refresh() {
      cache.clear();
      await refreshDaily();
      return show(current);
    },
    async load() {
      await refreshDaily();
      return show(current);
    },
  };
}
