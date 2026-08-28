// Collected verbatim, interpreted nowhere. Paste into javascript_tool.
//
// Returns every result row's aria-label and visible text plus two page facts
// the ingester asserts on. If Google restructures its markup this file is the
// only thing that breaks, and it breaks loudly by returning zero rows.
(() => {
  const bodyText = document.body.innerText;
  const rows = [...document.querySelectorAll('li')]
    .map((li) => {
      const labelled = li.querySelector('[aria-label]');
      const aria = labelled && labelled.getAttribute('aria-label');
      if (!aria || !/^From /.test(aria)) return null;
      return {
        aria,
        text: li.innerText.replace(/ /g, ' ').trim(),
      };
    })
    .filter(Boolean);

  return {
    url: location.href,
    title: document.title,
    sortedBy: (bodyText.match(/Sorted by[^\n]*/) || [null])[0],
    // Best and Cheapest are two result sets, not two sort orders. The
    // ingester refuses any page whose selected tab is not Cheapest.
    activeTab: (() => {
      const tab = document.querySelector('[role="tab"][aria-selected="true"]');
      return tab ? tab.innerText.split('\n')[0].trim() : null;
    })(),
    filters: (bodyText.match(/All filters \(\d+\)/) || [null])[0],
    legFields: [...document.querySelectorAll('input')]
      .map((i) => i.value)
      .filter(Boolean),
    rowCount: rows.length,
    rows,
  };
})()
