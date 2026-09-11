import { t, useLocale } from './i18n';
import { useMemo, useState, type ReactNode } from 'react';
import { createColumnHelper, tableFeatures, useTable, type RowData } from '@tanstack/react-table';
import { ArrowDown, ArrowUp, Search } from 'lucide-react';
import { Empty } from './ui';

// Only the currently fetched page is filtered or sorted; no table feature fetches more rows.
const features = tableFeatures({});
export interface TableColumn<T> { id: string; title: string; render: (row: T) => ReactNode; value?: (row: T) => string | number | bigint | null }
export function DataTable<T extends RowData>({ rows, columns, searchText, name }: { rows: T[]; columns: TableColumn<T>[]; searchText?: (row: T) => string; name: string }) {
  useLocale();
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<{ key: string; direction: number } | null>(null);
  const data = useMemo(() => {
    const filtered = searchText ? rows.filter(row => searchText(row).toLowerCase().includes(search.toLowerCase())) : rows;
    if (!sort) return filtered;
    // Null values stay last in both directions instead of being treated as zero.
    const column = columns.find(item => item.id === sort.key);
    return [...filtered].sort((a, b) => {
      const left = column?.value?.(a), right = column?.value?.(b);
      if (left == null || right == null) return left == null ? right == null ? 0 : 1 : -1;
      return (left < right ? -1 : left > right ? 1 : 0) * sort.direction;
    });
  }, [rows, searchText, search, sort, columns]);
  // Headless definitions bind only the supplied page; no table plugin owns fetching or pagination.
  const definitions = useMemo(() => {
    const helper = createColumnHelper<typeof features, T>();
    return columns.map(column => helper.display({ id: column.id, header: column.title, cell: info => column.render(info.row.original) }));
  }, [columns]);
  const table = useTable({ features, columns: definitions, data });
  // User-visible scope prevents a page-local search from masquerading as a global result filter.
  return <div>{searchText && <div className="table-toolbar"><label className="search-field"><Search size={16} /><input aria-label={t("Search this page: {0}", [name])} placeholder={t("Search the current page")} value={search} onChange={event => setSearch(event.target.value)} /></label><span>{data.length} {t("of")} {rows.length} {t("on this page")}</span></div>}
    <div className="table-scroll"><table aria-label={name}><thead>{table.getHeaderGroups().map(group => <tr key={group.id}>
      {group.headers.map(header => { const column = columns.find(item => item.id === header.column.id)!; return <th key={header.id} aria-sort={sort?.key === column.id ? sort.direction > 0 ? 'ascending' : 'descending' : undefined}>
        {column.value ? <button className="sort-button" onClick={() => setSort({ key: column.id, direction: sort?.key === column.id ? -sort.direction : -1 })}>{column.title}{sort?.key === column.id ? sort.direction > 0 ? <ArrowUp size={13} /> : <ArrowDown size={13} /> : null}</button> : column.title}
      </th>; })}</tr>)}</thead>
      {/* Headless row rendering keeps semantic HTML and native assistive-technology support. */}
      <tbody>{table.getRowModel().rows.map(row => <tr key={row.id}>{row.getAllCells().map(cell => <td key={cell.id}><table.FlexRender cell={cell} /></td>)}</tr>)}</tbody>
    </table></div>{!data.length && <Empty title={t("No records")} detail={search ? t("Change the search on this page.") : t("Data will appear after the job completes.")} />}
  </div>;
}
