
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  AlertCircle,
  ArrowRight,
  BarChart3,
  BookOpen,
  Bot,
  ChartNoAxesCombined,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Database,
  FileText,
  Filter,
  Globe,
  History,
  LayoutDashboard,
  Layers3,
  MapPin,
  Newspaper,
  Play,
  Rss,
  RefreshCw,
  Search,
  Settings,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Tags,
  X,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import './App.css'

const API_BASE = import.meta.env.DEV ? '' : (import.meta.env.VITE_API_URL?.trim() || '')
const PAGE_SIZE = 8

const CATEGORY_COLORS = [
  '#336cff', '#11a878', '#12a7c7', '#8054e8', '#e65c9a',
  '#f29b38', '#7596c8', '#e65c5c', '#7c8da8', '#14a6a1', '#8a75df',
]

const CATEGORY_NAMES = [
  'Politics', 'Business', 'Technology', 'Sports', 'Health',
  'Education', 'Entertainment', 'Science', 'Environment', 'World', 'Other',
]

const NAV_ITEMS = [
  { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
  { id: 'all-news', label: 'News Collection', icon: Rss },
  { id: 'category', label: 'News Segregation', icon: Layers3 },
  { id: 'geography', label: 'Geographic Filtering', icon: MapPin },
  { id: 'analytics', label: 'NLP Agent / Analytics', icon: ChartNoAxesCombined },
  { id: 'agents', label: 'AI Agent Monitoring', icon: Bot },
  { id: 'history', label: 'Collection History', icon: History },
  { id: 'settings', label: 'Settings', icon: Settings },
]

const EMPTY_GEO = { countries: [], states: [], districts: [] }
const EMPTY_FILTERS = {
  search: '',
  category: '',
  country: '',
  state: '',
  district: '',
  source: '',
}

const FRIENDLY_API_ERROR =
  'Cannot reach the INFORVEX API. Check the configured API URL and backend health endpoint.'

async function request(path, options = {}) {
  let response

  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    })
  } catch {
    throw new Error(FRIENDLY_API_ERROR)
  }

  if (!response.ok) {
    const body = await response.text().catch(() => '')

    if (
      response.status >= 500 &&
      /proxy error|econnrefused|socket hang up|connecterror/i.test(body)
    ) {
      throw new Error(FRIENDLY_API_ERROR)
    }

    let message = `Request failed (${response.status})`

    try {
      const parsed = JSON.parse(body)
      message = parsed.detail || parsed.message || message
    } catch {
      if (body && response.status < 500) {
        message = body.slice(0, 180)
      }
    }

    throw new Error(message)
  }

  return response.json()
}

function asArray(value) {
  if (Array.isArray(value)) return value
  if (Array.isArray(value?.value)) return value.value
  if (Array.isArray(value?.items)) return value.items
  return []
}

function normalizeArticles(value) {
  if (Array.isArray(value)) {
    return { items: value, total: value.length }
  }

  const items = asArray(value)

  return {
    items,
    total: Number(value?.total ?? value?.count ?? items.length),
  }
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString()
}

function formatDate(value, includeTime = false) {
  if (!value) return 'Not recorded'

  const timestamp = String(value).trim()
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(timestamp)
  const date = new Date(hasTimezone ? timestamp : `${timestamp}Z`)

  if (Number.isNaN(date.getTime())) return 'Not recorded'

  return date.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    ...(includeTime
      ? { dateStyle: 'medium', timeStyle: 'short' }
      : { dateStyle: 'medium' }),
  })
}

function formatArticleDate(article) {
  if (article.publication_time) {
    return `Published ${formatDate(article.publication_time, true)}`
  }

  if (article.first_fetched_at) {
    return `Collected ${formatDate(article.first_fetched_at, true)}`
  }

  return 'Publication time unavailable'
}

function getLocation(article) {
  return (
    [article.district, article.state, article.country].filter(Boolean).join(', ') ||
    'Location unknown'
  )
}

function getStatusClass(status) {
  const normalized = String(status || 'unknown').toLowerCase().replaceAll(' ', '_')

  if (['completed', 'success', 'healthy'].includes(normalized)) return 'success'

  if (
    ['running', 'partial', 'completed_with_errors', 'not_checked'].includes(normalized)
  ) {
    return 'warning'
  }

  if (['failed', 'error'].includes(normalized)) return 'danger'

  return 'neutral'
}

function categoryColor(name) {
  const index = CATEGORY_NAMES.indexOf(name)
  return CATEGORY_COLORS[index >= 0 ? index : CATEGORY_COLORS.length - 1]
}

function Brand() {
  return (
    <div className="brand">
      <div className="brand-mark">
        <Globe size={25} strokeWidth={2.2} />
      </div>
      <div className="brand-copy">
        <strong>INFORVEX</strong>
        <span>Multi-Agent News Management System</span>
      </div>
    </div>
  )
}

function NavButton({ item, active, onClick }) {
  const Icon = item.icon

  return (
    <button
      className={`nav-item ${active ? 'active' : ''}`}
      onClick={onClick}
      type="button"
    >
      <Icon size={19} strokeWidth={1.9} />
      <span>{item.label}</span>
      {active && <span className="nav-active-mark" />}
    </button>
  )
}

function SidebarNavGroup({ label, items, activePage, onNavigate }) {
  return (
    <div className="sidebar-nav-group">
      <div className="sidebar-section-label">{label}</div>
      <div className="primary-nav">
        {items.map((item) => (
          <NavButton
            key={item.id}
            item={item}
            active={activePage === item.id}
            onClick={() => onNavigate(item.id)}
          />
        ))}
      </div>
    </div>
  )
}

function StatCard({ icon: Icon, label, value, helper, tone = 'blue' }) {
  return (
    <article className={`stat-card tone-${tone}`}>
      <div className="stat-icon">
        <Icon size={21} strokeWidth={2} />
      </div>
      <div className="stat-content">
        <span className="stat-label">{label}</span>
        <strong className="stat-value">{value ?? '—'}</strong>
        {helper && <span className="stat-helper">{helper}</span>}
      </div>
    </article>
  )
}

function SectionHeading({
  eyebrow,
  title,
  action,
  onAction,
  actionLabel = 'View all',
}) {
  return (
    <div className="section-heading">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h2>{title}</h2>
      </div>
      {action && (
        <button type="button" className="text-action" onClick={onAction}>
          {actionLabel}
          <ArrowRight size={15} />
        </button>
      )}
    </div>
  )
}

function SelectField({
  label,
  value,
  onChange,
  options,
  placeholder,
  disabled = false,
}) {
  return (
    <label className={`select-field ${disabled ? 'disabled' : ''}`}>
      <span>{label}</span>
      <div className="select-control">
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
        >
          <option value="">{placeholder}</option>
          {options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
        <ChevronDown size={15} />
      </div>
    </label>
  )
}

function GeoFilterBar({
  filters,
  appliedFilters = filters,
  geoOptions,
  onUpdate,
  onApply,
  onClear,
  compact = false,
  resultCount = null,
  showActions = true,
}) {
  const geoKeys = ['country', 'state', 'district']

  const pending = geoKeys.some(
    (key) => (filters[key] || '') !== (appliedFilters[key] || ''),
  )

  const appliedLocation = [
    appliedFilters.district,
    appliedFilters.state,
    appliedFilters.country,
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <div className={`geo-filter-bar ${compact ? 'compact' : ''}`}>
      <SelectField
        label="Country"
        value={filters.country}
        onChange={(value) => onUpdate('country', value)}
        options={geoOptions.countries}
        placeholder="All countries"
      />

      <SelectField
        label="State / Province"
        value={filters.state}
        onChange={(value) => onUpdate('state', value)}
        options={geoOptions.states}
        placeholder="All states"
        disabled={!filters.country}
      />

      <SelectField
        label="District"
        value={filters.district}
        onChange={(value) => onUpdate('district', value)}
        options={geoOptions.districts}
        placeholder="All districts"
        disabled={!filters.state}
      />

      {showActions && (
        <div className="filter-actions">
          <button type="button" className="button button-primary" onClick={onApply}>
            <Filter size={16} />
            Apply filter
          </button>

          {onClear && (
            <button type="button" className="button button-quiet" onClick={onClear}>
              Clear
            </button>
          )}
        </div>
      )}

      <div
        className={`geo-filter-feedback ${pending ? 'pending' : 'applied'}`}
        role="status"
        aria-live="polite"
      >
        {pending
          ? 'Selection changed — click Apply filter to update the news list.'
          : appliedLocation
            ? `Applied location: ${appliedLocation}${
                resultCount === null
                  ? ''
                  : ` · ${formatNumber(resultCount)} matching articles`
              }. Articles without stored location data are excluded.`
            : 'No location filter applied. Choose a country to narrow the news list.'}
      </div>
    </div>
  )
}

function activeFilterLabels(filters) {
  const labels = []

  if (filters.search) labels.push(`Search: ${filters.search}`)
  if (filters.source) labels.push(`Source: ${filters.source}`)
  if (filters.category) labels.push(`Category: ${filters.category}`)
  if (filters.country) labels.push(`Country: ${filters.country}`)
  if (filters.state) labels.push(`State: ${filters.state}`)
  if (filters.district) labels.push(`District: ${filters.district}`)

  return labels
}

function EmptyNewsState({
  emptyText,
  activeFilters = EMPTY_FILTERS,
  onClear,
  onRetry,
}) {
  const labels = activeFilterLabels(activeFilters)

  return (
    <div className="page-state empty-news-state">
      <Newspaper size={29} />
      <strong>No articles match your filters</strong>
      <span>
        {emptyText ||
          'Try broadening your search or removing one of the active filters.'}
      </span>

      {labels.length > 0 && (
        <div className="active-filter-list" aria-label="Active filters">
          {labels.map((label) => (
            <span className="active-filter-chip" key={label}>
              {label}
            </span>
          ))}
        </div>
      )}

      <div className="empty-state-actions">
        {onClear && (
          <button type="button" className="button button-primary" onClick={onClear}>
            Clear all filters
          </button>
        )}

        {onRetry && (
          <button type="button" className="button button-outline" onClick={onRetry}>
            Refresh news
          </button>
        )}
      </div>
    </div>
  )
}

function ReaderQuickFilters({
  filters,
  appliedFilters,
  categories,
  sources,
  geoOptions,
  onUpdate,
  onApply,
  onClear,
  resultCount,
}) {
  const keys = ['search', 'source', 'category', 'country', 'state', 'district']

  const pending = keys.some(
    (key) => (filters[key] || '') !== (appliedFilters[key] || ''),
  )

  return (
    <div className="reader-quick-filters">
      <label className="input-field reader-search-field">
        <span>Search headlines</span>
        <div className="quick-search-control">
          <Search size={15} />
          <input
            value={filters.search}
            onChange={(event) => onUpdate('search', event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') onApply()
            }}
            placeholder="Search a topic, person or event…"
          />
        </div>
      </label>

      <SelectField
        label="Source"
        value={filters.source}
        onChange={(value) => onUpdate('source', value)}
        options={sources}
        placeholder="All sources"
      />

      <SelectField
        label="Category"
        value={filters.category}
        onChange={(value) => onUpdate('category', value)}
        options={categories}
        placeholder="All topics"
      />

      <div className="reader-filter-actions">
        <button type="button" className="button button-primary" onClick={onApply}>
          <Filter size={15} />
          Apply filters
        </button>
      </div>

      <div className="reader-location-heading">
        <MapPin size={15} />
        <strong>Filter by location</strong>
        <span>Matches use saved article metadata.</span>
      </div>

      <GeoFilterBar
        filters={filters}
        appliedFilters={appliedFilters}
        resultCount={resultCount}
        geoOptions={geoOptions}
        onUpdate={onUpdate}
        onApply={onApply}
        onClear={onClear}
        showActions={false}
      />

      <p
        className={`reader-filter-status ${pending ? 'pending' : 'applied'}`}
        role="status"
        aria-live="polite"
      >
        {pending
          ? 'You have changed filters. Apply them to update your news feed.'
          : `${formatNumber(resultCount)} matching articles${
              appliedFilters.source ? ` from ${appliedFilters.source}` : ''
            }.`}
      </p>
    </div>
  )
}

function ArticleRow({ article, compact = false }) {
  const category = article.category || 'Other'
  const color = categoryColor(category)

  return (
    <article className={`article-row ${compact ? 'compact' : ''}`}>
      <div
        className="article-glyph"
        style={{
          '--category-color': color,
          '--category-tint': `${color}16`,
        }}
      >
        <Newspaper size={21} />
      </div>

      <div className="article-main">
        <div className="article-meta-top">
          <span
            className="category-pill"
            style={{
              '--category-color': color,
              '--category-tint': `${color}18`,
            }}
          >
            {category}
          </span>

          <time
            className="article-date"
            dateTime={article.publication_time || article.first_fetched_at}
          >
            <Clock3 size={12} />
            {formatArticleDate(article)}
          </time>
        </div>

        <a
          className="article-title"
          href={article.canonical_url}
          target="_blank"
          rel="noreferrer"
        >
          {article.title}
        </a>

        {article.summary && <p className="article-summary">{article.summary}</p>}

        <div className="article-footer">
          <span className="article-publisher">
            <BookOpen size={13} />
            {article.source_name || 'Unknown source'}
          </span>

          <span className="article-location">
            <MapPin size={13} />
            {getLocation(article)}
          </span>
        </div>
      </div>
    </article>
  )
}

function NewsTable({
  articles,
  loading,
  onRetry,
  onClear,
  activeFilters,
  emptyText = 'Try broadening your search or removing one of the active filters.',
}) {
  if (loading) {
    return (
      <div className="page-state">
        <span className="spinner" />
        Loading news from your database…
      </div>
    )
  }

  if (!articles.length) {
    return (
      <EmptyNewsState
        emptyText={emptyText}
        activeFilters={activeFilters}
        onClear={onClear}
        onRetry={onRetry}
      />
    )
  }

  return (
    <div className="news-table-wrap">
      <table className="news-table">
        <thead>
          <tr>
            <th>Article</th>
            <th>Source</th>
            <th>Category</th>
            <th>Time</th>
            <th>Location</th>
          </tr>
        </thead>

        <tbody>
          {articles.map((article) => (
            <tr key={article.id}>
              <td>
                <a
                  href={article.canonical_url}
                  target="_blank"
                  rel="noreferrer"
                  className="table-article-title"
                >
                  {article.title}
                </a>
                <span className="table-summary">
                  {article.summary || 'No summary provided by source.'}
                </span>
              </td>

              <td>{article.source_name || 'Unknown'}</td>

              <td>
                <span
                  className="category-pill"
                  style={{
                    '--category-color': categoryColor(article.category),
                    '--category-tint': `${categoryColor(article.category)}18`,
                  }}
                >
                  {article.category || 'Other'}
                </span>
              </td>

              <td>{formatArticleDate(article)}</td>
              <td>{getLocation(article)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Pagination({ page, pageSize, total, onPageChange }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="pagination">
      <span>
        Showing {total === 0 ? 0 : page * pageSize + 1}–
        {Math.min((page + 1) * pageSize, total)} of {formatNumber(total)} articles
      </span>

      <div>
        <button
          type="button"
          className="icon-button"
          onClick={() => onPageChange(Math.max(0, page - 1))}
          disabled={page === 0}
          aria-label="Previous page"
        >
          <ChevronLeft size={17} />
        </button>

        <span className="page-indicator">
          Page {page + 1} of {pages}
        </span>

        <button
          type="button"
          className="icon-button"
          onClick={() => onPageChange(Math.min(pages - 1, page + 1))}
          disabled={(page + 1) * pageSize >= total}
          aria-label="Next page"
        >
          <ChevronRight size={17} />
        </button>
      </div>
    </div>
  )
}

function AgentPanel({ agents }) {
  const agentDefinitions = [
    ['Orchestration Agent', 'Orchestration Agent', 'Coordinates the collection workflow'],
    ['Web News Scraping Agent', 'Web Scraping Agent', 'Retrieves news from configured feeds'],
    ['Database Management Agent', 'Database Agent', 'Validates and stores article records'],
    ['News Segregation Agent', 'Segregation Agent', 'Applies explainable category rules'],
    ['Geographical Filtering Agent', 'Geography Agent', 'Checks validated geographic metadata'],
    ['News Analytics Agent', 'NLP Agent', 'Analyzes stored articles for sentiment and entities'],
  ]

  const agentIcons = {
    'Orchestration Agent': Bot,
    'Web News Scraping Agent': Rss,
    'Database Management Agent': Database,
    'News Segregation Agent': Layers3,
    'Geographical Filtering Agent': MapPin,
    'News Analytics Agent': ChartNoAxesCombined,
  }

  return (
    <div className="agent-grid">
      {agentDefinitions.map(([identifier, name, description]) => {
        const agent = agents.find(
          (item) =>
            item.name === identifier ||
            (identifier === 'News Analytics Agent' && item.name === 'NLP Agent'),
        )

        const status = agent?.status
        const AgentIcon = agentIcons[identifier]

        return (
          <article className="agent-card" key={identifier}>
            <div className="agent-card-icon">
              <AgentIcon size={20} strokeWidth={2} />
            </div>

            <div className="agent-card-heading">
              <strong>{name}</strong>
              <span className={`status-badge ${getStatusClass(status)}`}>
                <i />
                {status || 'no execution data'}
              </span>
            </div>

            <p>{description}</p>

            <div className="agent-stat-line">
              <span>Reported count</span>
              <b>
                {agent ? formatNumber(agent.processed_count) : 'No executions recorded'}
              </b>
            </div>

            <div className="agent-stat-line">
              <span>Last execution</span>
              <b>
                {agent
                  ? formatDate(agent.last_execution, true)
                  : 'No execution recorded'}
              </b>
            </div>

            {agent?.error && (
              <div className="agent-error">
                <AlertCircle size={14} />
                {agent.error}
              </div>
            )}
          </article>
        )
      })}
    </div>
  )
}

function SourcePanel({ sources }) {
  return (
    <div className="source-list">
      {sources.map((source) => (
        <article className="source-row" key={source.url}>
          <div className={`source-icon ${getStatusClass(source.status)}`}>
            <Globe size={18} />
          </div>

          <div className="source-info">
            <strong>{source.name || source.url}</strong>
            <span>{source.url}</span>
            {source.error && <small className="source-error">{source.error}</small>}
          </div>

          <div className="source-metrics">
            <b>{formatNumber(source.articles)}</b>
            <span>stored in this source</span>
          </div>

          <span className={`status-badge ${getStatusClass(source.status)}`}>
            <i />
            {String(source.status || 'not checked').replaceAll('_', ' ')}
          </span>
        </article>
      ))}

      {!sources.length && (
        <div className="page-state compact-state">
          <Server size={23} />
          <strong>No source records available</strong>
          <span>Configure permitted RSS/Atom feeds in backend/.env.</span>
        </div>
      )}
    </div>
  )
}

function CollectionHistoryPanel({ history }) {
  return (
    <div className="history-table-wrap">
      <table className="news-table">
        <thead>
          <tr>
            <th>Run</th>
            <th>Started</th>
            <th>Retrieved</th>
            <th>Inserted</th>
            <th>Duplicates</th>
            <th>Failed</th>
            <th>Status</th>
          </tr>
        </thead>

        <tbody>
          {history.map((run) => (
            <tr key={run.id}>
              <td>#{run.id}</td>
              <td>{formatDate(run.started_at, true)}</td>
              <td>{formatNumber(run.retrieved)}</td>
              <td>{formatNumber(run.inserted)}</td>
              <td>{formatNumber(run.duplicates)}</td>
              <td>{formatNumber(run.failed)}</td>
              <td>
                <span className={`status-badge ${getStatusClass(run.status)}`}>
                  <i />
                  {run.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {!history.length && (
        <div className="page-state compact-state">
          No collection history recorded.
        </div>
      )}
    </div>
  )
}

function AgentMonitoringPage({ agents, loading }) {
  return (
    <section className="page-content monitoring-page">
      <section className="panel page-intro-panel">
        <div className="page-intro-icon blue-intro">
          <Bot size={24} />
        </div>
        <div>
          <h2>AI Agent Monitoring</h2>
          <p>Live execution details for the six INFORVEX agents.</p>
        </div>
      </section>

      {loading && !agents.length ? (
        <div className="page-state">
          <span className="spinner" />
          Loading agent status…
        </div>
      ) : (
        <section className="panel">
          <div className="agent-summary-strip">
            <div>
              <span>Agents</span>
              <strong>{agents.length}</strong>
            </div>
            <div>
              <span>Completed</span>
              <strong>
                {agents.filter((agent) => agent.status === 'completed').length}
              </strong>
            </div>
            <div>
              <span>Running</span>
              <strong>
                {agents.filter((agent) => agent.status === 'running').length}
              </strong>
            </div>
            <div>
              <span>Failed</span>
              <strong>
                {agents.filter((agent) => ['failed', 'error'].includes(agent.status)).length}
              </strong>
            </div>
          </div>

          <AgentPanel agents={agents} />
        </section>
      )}
    </section>
  )
}

function CollectionHistoryPage({ history, loading }) {
  return (
    <section className="page-content history-page">
      <section className="panel page-intro-panel">
        <div className="page-intro-icon purple-intro">
          <History size={24} />
        </div>
        <div>
          <h2>Collection History</h2>
          <p>
            Stored collection runs and their reported retrieval, insertion,
            duplicate, and failure counts.
          </p>
        </div>
      </section>

      <section className="panel">
        <SectionHeading eyebrow="STORED RUNS" title="Collection runs" />

        {loading && !history.length ? (
          <div className="page-state">
            <span className="spinner" />
            Loading collection history…
          </div>
        ) : (
          <CollectionHistoryPanel history={history} />
        )}
      </section>
    </section>
  )
}

function AnalyticsPage({ analytics, loading, onRetry }) {
  if (loading && !analytics) {
    return (
      <div className="page-state">
        <span className="spinner" />
        Loading machine-generated analytics…
      </div>
    )
  }

  if (!analytics) {
    return (
      <div className="page-state">
        <ChartNoAxesCombined size={24} />
        <strong>Analytics are unavailable</strong>
        <span>Refresh to retry the analytics API.</span>
        <button className="button button-outline" type="button" onClick={onRetry}>
          Retry
        </button>
      </div>
    )
  }

  if (!analytics.enabled) {
    return (
      <div className="page-state">
        <ChartNoAxesCombined size={24} />
        <strong>News Analytics Agent is disabled</strong>
        <span>
          Set ANALYTICS_ENABLED=true in the backend environment, then refresh.
          No synthetic results are shown.
        </span>
      </div>
    )
  }

  const chartColors = [
    '#55d6ff',
    '#8e7dff',
    '#38d39f',
    '#ffb86b',
    '#f277a8',
  ]

  const publisherChartHeight = Math.max(280, analytics.publishers.length * 38)

  const publisherName = (name) =>
    name.length > 24 ? `${name.slice(0, 23)}…` : name

  return (
    <section className="analytics-page">
      <div className="analytics-disclaimer">
        <ChartNoAxesCombined size={17} />
        <span>
          Machine-generated estimates from analyzed stored articles. Results may
          be incomplete until the optional agent has processed the collection.
        </span>
      </div>

      <div className="stats-grid analytics-metrics">
        <StatCard
          icon={FileText}
          label="Analyzed articles"
          value={formatNumber(analytics.analyzed_articles)}
          helper={`of ${formatNumber(analytics.total_articles)} stored articles`}
          tone="blue"
        />

        <StatCard
          icon={BarChart3}
          label="Keywords extracted"
          value={formatNumber(analytics.keywords.length)}
          helper="TF-IDF and cleaned text"
          tone="purple"
        />
      </div>

      <div className="analytics-grid">
        <section className="panel analytics-chart-panel">
          <SectionHeading
            eyebrow="SENTIMENT"
            title="Estimated sentiment distribution"
          />
          <div className="chart-box">
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={analytics.sentiment}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={62}
                  outerRadius={88}
                  paddingAngle={4}
                >
                  {analytics.sentiment.map((entry, index) => (
                    <Cell key={entry.name} fill={chartColors[index]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="panel analytics-chart-panel">
          <SectionHeading eyebrow="NEWS VOLUME" title="Daily article trend" />
          <div className="chart-box">
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={analytics.daily_trends}>
                <defs>
                  <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#55d6ff" stopOpacity=".45" />
                    <stop offset="100%" stopColor="#55d6ff" stopOpacity="0" />
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" hide />
                <YAxis
                  allowDecimals={false}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="#55d6ff"
                  fill="url(#trendFill)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="panel analytics-chart-panel">
          <SectionHeading eyebrow="KEYWORDS" title="Most frequent terms" />
          <div className="chart-box">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart
                data={analytics.keywords.slice(0, 8)}
                layout="vertical"
                margin={{ left: 20, right: 12 }}
              >
                <XAxis type="number" hide />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={90}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip />
                <Bar dataKey="value" fill="#8e7dff" radius={[0, 5, 5, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="panel analytics-chart-panel publisher-chart-panel">
          <SectionHeading eyebrow="PUBLISHERS" title="Publisher comparison" />
          <div className="chart-box publisher-chart-box">
            <ResponsiveContainer width="100%" height={publisherChartHeight}>
              <BarChart
                data={analytics.publishers}
                layout="vertical"
                margin={{ top: 8, right: 18, bottom: 8, left: 8 }}
              >
                <XAxis
                  type="number"
                  allowDecimals={false}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: '#CBD5E1', fontSize: 11 }}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={145}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: '#CBD5E1', fontSize: 11 }}
                  tickFormatter={publisherName}
                />
                <Tooltip
                  contentStyle={{
                    background: '#1E2D45',
                    border: '1px solid #334661',
                    color: '#F8FAFC',
                  }}
                  labelStyle={{ color: '#F8FAFC' }}
                  formatter={(value) => [formatNumber(value), 'Articles']}
                  labelFormatter={(label) => label}
                />
                <Bar dataKey="value" fill="#22D3EE" radius={[0, 5, 5, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      </div>

      <div className="analytics-lists">
        <section className="panel">
          <SectionHeading eyebrow="TOPICS" title="Category distribution" />
          <div className="analytics-list">
            {analytics.categories.map((item) => (
              <div className="analytics-list-row" key={item.name}>
                <span>{item.name}</span>
                <strong>{formatNumber(item.value)}</strong>
              </div>
            ))}
          </div>
        </section>
      </div>
    </section>
  )
}

function App() {
  const [activePage, setActivePage] = useState('dashboard')
  const [stats, setStats] = useState(null)
  const [articles, setArticles] = useState({ items: [], total: 0 })
  const [agents, setAgents] = useState([])
  const [sources, setSources] = useState([])
  const [history, setHistory] = useState([])
  const [systemStatus, setSystemStatus] = useState(null)
  const [analytics, setAnalytics] = useState(null)
  const [geoOptions, setGeoOptions] = useState(EMPTY_GEO)
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [appliedFilters, setAppliedFilters] = useState(EMPTY_FILTERS)
  const [pageIndex, setPageIndex] = useState(0)
  const [loading, setLoading] = useState(true)
  const [collecting, setCollecting] = useState(false)
  const [refreshTick, setRefreshTick] = useState(0)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const [adminToken, setAdminToken] = useState(
    () => sessionStorage.getItem('inforvex_admin_token') || '',
  )

  const [tokenSaved, setTokenSaved] = useState(
    () => Boolean(sessionStorage.getItem('inforvex_admin_token')),
  )

  const pageSize = PAGE_SIZE

  const categoryRows = useMemo(() => {
    const values = stats?.categories || []
    return [...values].sort((a, b) => b.value - a.value)
  }, [stats])

  const queryForArticles = useMemo(() => {
    const params = new URLSearchParams()

    Object.entries(appliedFilters).forEach(([key, value]) => {
      if (value) params.set(key, value)
    })

    if (activePage === 'category' && appliedFilters.category) {
      params.set('category', appliedFilters.category)
    }

    params.set('limit', String(pageSize))
    params.set('offset', String(pageIndex * pageSize))

    return params.toString()
  }, [activePage, appliedFilters, pageIndex, pageSize])

  const reload = useCallback(() => {
    setRefreshTick((value) => value + 1)
  }, [])

  // Load data required by the currently selected page.
  useEffect(() => {
    let alive = true

    const timer = window.setTimeout(async () => {
      try {
        if (activePage === 'dashboard') {
          const [
            nextStats,
            nextArticles,
            nextSources,
            nextHistory,
            nextSystemStatus,
          ] = await Promise.all([
            request('/api/dashboard/stats'),
            request(`/api/news?${queryForArticles}`),
            request('/api/sources'),
            request('/api/collection/history'),
            request('/api/system/status'),
          ])

          if (!alive) return

          setStats(nextStats)
          setArticles(normalizeArticles(nextArticles))
          setSources(asArray(nextSources))
          setHistory(asArray(nextHistory))
          setSystemStatus(nextSystemStatus)
        } else if (activePage === 'all-news') {
          const [nextArticles, nextStats, nextSources] = await Promise.all([
            request(`/api/news?${queryForArticles}`),
            request('/api/dashboard/stats'),
            request('/api/sources'),
          ])

          if (!alive) return

          setArticles(normalizeArticles(nextArticles))
          setStats(nextStats)
          setSources(asArray(nextSources))
        } else if (
          activePage === 'category' ||
          activePage === 'geography'
        ) {
          const [nextArticles, nextStats] = await Promise.all([
            request(`/api/news?${queryForArticles}`),
            request('/api/dashboard/stats'),
          ])

          if (!alive) return

          setArticles(normalizeArticles(nextArticles))
          setStats(nextStats)
        } else if (activePage === 'analytics') {
          const nextAnalytics = await request('/api/analytics/summary')

          if (!alive) return

          setAnalytics(nextAnalytics)
        } else if (
          activePage === 'agents' ||
          activePage === 'history' ||
          activePage === 'settings'
        ) {
          const [
            nextAgents,
            nextSources,
            nextHistory,
            nextStats,
            nextSystemStatus,
          ] = await Promise.all([
            request('/api/agents/status'),
            request('/api/sources'),
            request('/api/collection/history'),
            request('/api/dashboard/stats'),
            request('/api/system/status'),
          ])

          if (!alive) return

          setAgents(asArray(nextAgents))
          setSources(asArray(nextSources))
          setHistory(asArray(nextHistory))
          setStats(nextStats)
          setSystemStatus(nextSystemStatus)
        }

        if (alive) setError('')
      } catch (err) {
        if (alive) {
          setError(err.message || FRIENDLY_API_ERROR)
        }
      } finally {
        if (alive) setLoading(false)
      }
    }, 0)

    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [activePage, queryForArticles, refreshTick])

  // Refresh the Settings monitor every five seconds.
  useEffect(() => {
    if (activePage !== 'settings') return undefined

    const timerId = window.setInterval(() => {
      setRefreshTick((value) => value + 1)
    }, 5000)

    return () => window.clearInterval(timerId)
  }, [activePage])

  // Load hierarchical geographic dropdown options.
  useEffect(() => {
    let alive = true
    const params = new URLSearchParams()

    if (filters.country) params.set('country', filters.country)
    if (filters.state) params.set('state', filters.state)

    const timer = window.setTimeout(() => {
      request(`/api/geo/options${params.size ? `?${params}` : ''}`)
        .then((options) => {
          if (alive) {
            setGeoOptions({
              countries: options.countries || [],
              states: options.states || [],
              districts: options.districts || [],
            })
          }
        })
        .catch(() => {
          if (alive) setGeoOptions(EMPTY_GEO)
        })
    }, 0)

    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [filters.country, filters.state, refreshTick])

  const navigate = (page) => {
    if (page === activePage) return

    setLoading(true)
    setError('')
    setActivePage(page)
    setPageIndex(0)

    if (page === 'category' || page === 'dashboard') {
      const next = { ...appliedFilters, category: '' }
      setFilters(next)
      setAppliedFilters(next)
    }
  }

  const updateFilter = (key, value) => {
    setFilters((current) => ({
      ...current,
      [key]: value,
      ...(key === 'country' ? { state: '', district: '' } : {}),
      ...(key === 'state' ? { district: '' } : {}),
    }))
  }

  const applyFilters = (overrides = {}) => {
    const next = { ...filters, ...overrides }

    setFilters(next)
    setAppliedFilters(next)
    setPageIndex(0)
    setLoading(true)
    setNotice('')
  }

  const clearFilters = () => {
    setFilters(EMPTY_FILTERS)
    setAppliedFilters(EMPTY_FILTERS)
    setPageIndex(0)
    setLoading(true)
  }

  const saveAdminToken = () => {
    const token = adminToken.trim()

    if (!token) {
      setError('Please enter the admin token.')
      return
    }

    sessionStorage.setItem('inforvex_admin_token', token)
    setAdminToken(token)
    setTokenSaved(true)
    setError('')
    setNotice('Admin token saved for this browser session.')
  }

  const clearAdminToken = () => {
    sessionStorage.removeItem('inforvex_admin_token')
    setAdminToken('')
    setTokenSaved(false)
    setNotice('Admin token cleared.')
  }

  const collect = async () => {
    if (collecting) return

    setCollecting(true)
    setError('')
    setNotice('Collection is running…')

    try {
      const token = sessionStorage.getItem('inforvex_admin_token')

      if (!token) {
        throw new Error(
          'Save your admin token in Settings before running collection.',
        )
      }

      const result = await request('/api/collection/run', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })

      setNotice(
        `Collection ${result.status}: ${formatNumber(result.retrieved)} retrieved · ${formatNumber(result.inserted)} new · ${formatNumber(result.duplicates)} duplicates · ${formatNumber(result.failed)} failures`,
      )

      setLoading(true)
      reload()
    } catch (err) {
      setError(err.message || FRIENDLY_API_ERROR)
      setNotice('')
    } finally {
      setCollecting(false)
    }
  }

  const pageMeta = {
    dashboard: [
      'Your News Feed',
      'Browse recent stories, then narrow them by publisher, topic, or location.',
    ],
    category: [
      'News Categories',
      'Explore the articles stored in your database by their assigned category.',
    ],
    geography: [
      'Regional News',
      'Filter articles by verified country, state or province, and district metadata.',
    ],
    'all-news': [
      'All News',
      'Search and review the complete article collection with filters and pagination.',
    ],
    settings: [
      'Settings & Agent Monitor',
      'Review agent execution, configured sources, and recent collection history.',
    ],
    analytics: [
      'News Insights',
      'Explore machine-generated sentiment, keywords, trends, and publishers.',
    ],
    agents: [
      'AI Agent Monitoring',
      'Inspect the latest execution status reported by the multi-agent pipeline.',
    ],
    history: [
      'Collection History',
      'Review collection runs, retrieval counts, duplicates and failures.',
    ],
  }

  const [title, subtitle] = pageMeta[activePage]

  const setCategory = (category) => {
    const next = { ...filters, category }

    setFilters(next)
    setAppliedFilters(next)
    setActivePage('category')
    setPageIndex(0)
    setLoading(true)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Brand />

        <nav aria-label="Main navigation">
          <SidebarNavGroup
            label="WORKSPACE"
            items={NAV_ITEMS.slice(0, 5)}
            activePage={activePage}
            onNavigate={navigate}
          />

          <SidebarNavGroup
            label="OPERATIONS"
            items={NAV_ITEMS.slice(5)}
            activePage={activePage}
            onNavigate={navigate}
          />
        </nav>

        <div className="sidebar-spacer" />

        <div className="sidebar-status">
          <span className="pulse-dot" />
          <div>
            <strong>INFORVEX API</strong>
            <small>Local workspace</small>
          </div>
        </div>

        <div className="sidebar-footer">
          <ShieldCheck size={15} />
          <span>Transparent · Traceable · Source-based</span>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="mobile-brand">
            <Brand />
          </div>

          <div className="page-title-wrap">
            <div className="breadcrumbs">
              INFORVEX <span>/</span>{' '}
              {activePage === 'all-news' ? 'ALL NEWS' : activePage.toUpperCase()}
            </div>
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>

          <div className="topbar-actions">
            <button
              type="button"
              className="button button-outline refresh-button"
              onClick={() => {
                setLoading(true)
                reload()
              }}
            >
              <RefreshCw size={16} />
              Refresh
            </button>

            {activePage === 'settings' && (
              <button
                type="button"
                className="button button-primary collect-button"
                onClick={collect}
                disabled={collecting}
              >
                <Play size={15} fill="currentColor" />
                {collecting ? 'Collecting…' : 'Run collection now'}
              </button>
            )}
          </div>
        </header>

        {error && (
          <div className="feedback-banner error-banner">
            <AlertCircle size={19} />
            <div>
              <strong>Unable to load live data</strong>
              <span>{error}</span>
            </div>
            <button
              type="button"
              onClick={() => {
                setLoading(true)
                setError('')
                reload()
              }}
              aria-label="Retry requests"
            >
              <RefreshCw size={16} />
              Retry
            </button>
            <button
              className="dismiss-button"
              type="button"
              onClick={() => setError('')}
              aria-label="Dismiss error"
            >
              <X size={16} />
            </button>
          </div>
        )}

        {notice && (
          <div className="feedback-banner success-banner">
            <CheckCircle2 size={18} />
            <span>{notice}</span>
            <button
              className="dismiss-button"
              type="button"
              onClick={() => setNotice('')}
              aria-label="Dismiss notice"
            >
              <X size={16} />
            </button>
          </div>
        )}

        {activePage === 'dashboard' && (
          <>
            <section className="panel reader-filters-panel">
              <div className="reader-panel-heading">
                <div className="location-round-icon">
                  <Search size={20} />
                </div>
                <div>
                  <strong>
                    Discover the latest news from your configured sources.
                  </strong>
                  <span>
                    {stats?.last_collection
                      ? `Latest update ${formatDate(
                          stats.last_collection.completed_at ||
                            stats.last_collection.started_at,
                          true,
                        )}. Stored articles are shown below.`
                      : 'Stored articles from your configured sources are shown below.'}
                  </span>
                </div>
              </div>

              <ReaderQuickFilters
                filters={filters}
                appliedFilters={appliedFilters}
                categories={categoryRows.map((item) => item.name)}
                sources={[...new Set(sources.map((item) => item.name).filter(Boolean))].sort(
                  (a, b) => a.localeCompare(b),
                )}
                geoOptions={geoOptions}
                onUpdate={updateFilter}
                onApply={() => applyFilters()}
                onClear={clearFilters}
                resultCount={articles.total}
              />
            </section>

            <div className="dashboard-columns reader-dashboard-columns">
              <section className="panel panel-top-news">
                <SectionHeading
                  eyebrow="YOUR PERSONAL NEWS FEED"
                  title={
                    appliedFilters.source
                      ? `Latest from ${appliedFilters.source}`
                      : 'Latest headlines'
                  }
                  action
                  onAction={() => navigate('all-news')}
                  actionLabel="Browse all news"
                />

                {loading && !articles.items.length ? (
                  <div className="page-state short-state">
                    <span className="spinner" />
                    Loading your news feed…
                  </div>
                ) : articles.items.length ? (
                  <div className="article-list">
                    {articles.items.map((article) => (
                      <ArticleRow
                        article={article}
                        compact
                        key={article.id}
                      />
                    ))}
                  </div>
                ) : (
                  <EmptyNewsState
                    emptyText="Try another source, topic, or location. Articles with unknown locations cannot match a specific district."
                    activeFilters={appliedFilters}
                    onClear={clearFilters}
                    onRetry={reload}
                  />
                )}
              </section>

              <div className="right-stack">
                <section className="panel category-panel">
                  <SectionHeading
                    eyebrow="EXPLORE STORIES"
                    title="Browse by topic"
                    action
                    onAction={() => navigate('category')}
                    actionLabel="All topics"
                  />

                  <div className="topic-shortcuts">
                    {categoryRows.map((item) => (
                      <button
                        type="button"
                        className="topic-shortcut"
                        onClick={() => setCategory(item.name)}
                        key={item.name}
                      >
                        <span
                          className="legend-dot"
                          style={{ background: categoryColor(item.name) }}
                        />
                        <span>{item.name}</span>
                        <ArrowRight size={14} />
                      </button>
                    ))}
                  </div>
                </section>

                <section className="panel source-shortcuts-panel">
                  <SectionHeading
                    eyebrow="PUBLISHERS"
                    title="Browse by source"
                    action
                    onAction={() => navigate('all-news')}
                    actionLabel="All sources"
                  />

                  <div className="source-shortcuts">
                    {[
                      ...new Set(sources.map((item) => item.name).filter(Boolean)),
                    ]
                      .sort((a, b) => a.localeCompare(b))
                      .slice(0, 8)
                      .map((source) => (
                        <button
                          type="button"
                          className={`source-shortcut ${
                            appliedFilters.source === source ? 'selected' : ''
                          }`}
                          key={source}
                          onClick={() => applyFilters({ source })}
                        >
                          {source}
                        </button>
                      ))}
                  </div>

                  <p className="subtle-help">
                    Choose a publisher to read its latest available stories.
                    Manage feed URLs in Settings.
                  </p>
                </section>

                <section className="panel reader-note-panel">
                  <div className="reader-note-icon">
                    <MapPin size={18} />
                  </div>
                  <div>
                    <strong>News by location</strong>
                    <p>
                      Choose a country, then a state or district. Results
                      include only articles with matching saved location metadata.
                    </p>
                    <button
                      type="button"
                      className="text-action"
                      onClick={() => navigate('geography')}
                    >
                      Explore geographical news <ArrowRight size={14} />
                    </button>
                  </div>
                </section>
              </div>
            </div>
          </>
        )}

        {activePage === 'analytics' && (
          <AnalyticsPage
            analytics={analytics}
            loading={loading}
            onRetry={reload}
          />
        )}

        {activePage === 'category' && (
          <section className="page-content">
            <section className="panel page-intro-panel">
              <div className="page-intro-icon purple-intro">
                <Tags size={24} />
              </div>
              <div>
                <h2>Browse by category</h2>
                <p>
                  Select a category to view matching articles in the database.
                  Counts come from the current stored records.
                </p>
              </div>
            </section>

            <div className="category-cards">
              {categoryRows.map((item) => (
                <button
                  type="button"
                  key={item.name}
                  className={`category-card ${
                    appliedFilters.category === item.name ? 'selected' : ''
                  }`}
                  onClick={() =>
                    applyFilters({
                      category:
                        appliedFilters.category === item.name ? '' : item.name,
                    })
                  }
                >
                  <span
                    className="category-color-mark"
                    style={{ background: categoryColor(item.name) }}
                  />
                  <span className="category-card-name">{item.name}</span>
                  <strong>{formatNumber(item.value)}</strong>
                  <small>articles</small>
                </button>
              ))}
            </div>

            <section className="panel list-page-panel">
              <SectionHeading
                eyebrow="FILTERED ARTICLES"
                title={
                  appliedFilters.category
                    ? `${appliedFilters.category} news`
                    : 'All categories'
                }
              />

              <NewsTable
                articles={articles.items}
                loading={loading}
                onRetry={reload}
                onClear={clearFilters}
                activeFilters={appliedFilters}
              />

              <Pagination
                page={pageIndex}
                pageSize={pageSize}
                total={articles.total}
                onPageChange={(value) => {
                  setPageIndex(value)
                  setLoading(true)
                }}
              />
            </section>
          </section>
        )}

        {activePage === 'geography' && (
          <section className="page-content">
            <section className="panel page-intro-panel">
              <div className="page-intro-icon orange-intro">
                <MapPin size={24} />
              </div>
              <div>
                <h2>Explore news by location</h2>
                <p>
                  Choose a country, then state or province, then district. Only
                  verified article metadata is used for matches.
                </p>
              </div>
            </section>

            <section className="panel geofilter-page-panel">
              <SectionHeading
                eyebrow="HIERARCHICAL FILTER"
                title="Choose a location"
              />

              <GeoFilterBar
                filters={filters}
                appliedFilters={appliedFilters}
                resultCount={articles.total}
                geoOptions={geoOptions}
                onUpdate={updateFilter}
                onApply={() => applyFilters()}
                onClear={clearFilters}
              />

              <div className="metadata-note">
                <ShieldCheck size={17} />
                <span>
                  Reference data supplies dropdown choices; it does not assign
                  a location to an article. Articles with unknown locations
                  will not match a specific place.
                </span>
              </div>
            </section>

            <section className="panel list-page-panel">
              <SectionHeading
                eyebrow="LOCATION MATCHES"
                title={
                  getLocation({
                    country: appliedFilters.country,
                    state: appliedFilters.state,
                    district: appliedFilters.district,
                  }) === 'Location unknown'
                    ? 'Articles with available location data'
                    : getLocation({
                        country: appliedFilters.country,
                        state: appliedFilters.state,
                        district: appliedFilters.district,
                      })
                }
              />

              <NewsTable
                articles={articles.items}
                loading={loading}
                onRetry={reload}
                onClear={clearFilters}
                activeFilters={appliedFilters}
                emptyText="No articles with matching verified location data were found. This is different from the reference dropdown list."
              />

              <Pagination
                page={pageIndex}
                pageSize={pageSize}
                total={articles.total}
                onPageChange={(value) => {
                  setPageIndex(value)
                  setLoading(true)
                }}
              />
            </section>
          </section>
        )}

        {activePage === 'all-news' && (
          <section className="page-content">
            <section className="panel all-filters-panel">
              <SectionHeading
                eyebrow="SEARCH & FILTER"
                title="Refine the news collection"
              />

              <div className="all-filters-grid">
                <label className="input-field full-search">
                  <span>Search headlines or summaries</span>
                  <div>
                    <Search size={16} />
                    <input
                      value={filters.search}
                      onChange={(event) =>
                        updateFilter('search', event.target.value)
                      }
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') applyFilters()
                      }}
                      placeholder="Search news…"
                    />
                  </div>
                </label>

                <SelectField
                  label="Category"
                  value={filters.category}
                  onChange={(value) => updateFilter('category', value)}
                  options={categoryRows.map((item) => item.name)}
                  placeholder="All categories"
                />

                <SelectField
                  label="Source"
                  value={filters.source}
                  onChange={(value) => updateFilter('source', value)}
                  options={[
                    ...new Set(sources.map((item) => item.name).filter(Boolean)),
                  ]}
                  placeholder="All sources"
                />
              </div>

              <GeoFilterBar
                filters={filters}
                appliedFilters={appliedFilters}
                resultCount={articles.total}
                geoOptions={geoOptions}
                onUpdate={updateFilter}
                onApply={() => applyFilters()}
                onClear={clearFilters}
                compact
              />

              <div className="filter-footer">
                <span>{formatNumber(articles.total)} matching articles</span>
                <div>
                  <button
                    type="button"
                    className="button button-quiet"
                    onClick={clearFilters}
                  >
                    Clear all
                  </button>

                  <button
                    type="button"
                    className="button button-primary"
                    onClick={() => applyFilters()}
                  >
                    <SlidersHorizontal size={16} />
                    Apply filters
                  </button>
                </div>
              </div>
            </section>

            <section className="panel list-page-panel">
              <SectionHeading
                eyebrow="DATABASE RESULTS"
                title="All news articles"
              />

              <NewsTable
                articles={articles.items}
                loading={loading}
                onRetry={reload}
                onClear={clearFilters}
                activeFilters={appliedFilters}
              />

              <Pagination
                page={pageIndex}
                pageSize={pageSize}
                total={articles.total}
                onPageChange={(value) => {
                  setPageIndex(value)
                  setLoading(true)
                }}
              />
            </section>
          </section>
        )}

        {activePage === 'settings' && (
          <section className="page-content settings-page">
            <section className="panel page-intro-panel">
              <div className="page-intro-icon blue-intro">
                <Settings size={24} />
              </div>

              <div>
                <h2>Settings</h2>
                <p>
                  Application and administrative configuration for this
                  INFORVEX workspace.
                </p>
              </div>

              <button
                className="button button-outline"
                type="button"
                onClick={() => {
                  setLoading(true)
                  reload()
                }}
              >
                <RefreshCw size={15} />
                Refresh settings
              </button>
            </section>

            <section className="settings-metrics stats-grid">
              <StatCard
                icon={Newspaper}
                label="Stored unique articles"
                value={stats ? formatNumber(stats.articles) : '—'}
                helper="Articles saved after URL deduplication"
                tone="blue"
              />

              <StatCard
                icon={Activity}
                label="Collected today"
                value={stats ? formatNumber(stats.today) : '—'}
                helper="New records first fetched today"
                tone="green"
              />

              <StatCard
                icon={Server}
                label="Configured feeds"
                value={
                  systemStatus
                    ? formatNumber(systemStatus.configured_feed_count)
                    : '—'
                }
                helper="RSS / Atom source URLs"
                tone="purple"
              />

              <StatCard
                icon={MapPin}
                label="Verified geographic coverage"
                value={
                  stats ? formatNumber(stats.geographical_coverage) : '—'
                }
                helper="Articles with valid location metadata"
                tone="orange"
              />

              <StatCard
                icon={Database}
                label="Duplicates skipped"
                value={stats ? formatNumber(stats.duplicates) : '—'}
                helper="Repeated URLs not inserted again"
                tone="teal"
              />
            </section>

            <section className="panel">
              <SectionHeading
                eyebrow="ADMINISTRATION"
                title="Administrator authentication"
              />

              <p className="subtle-help">
                Enter the admin token configured in the INFORVEX backend to
                authorize collection runs.
              </p>

              <label className="input-field">
                <span>Admin API token</span>
                <input
                  type="password"
                  value={adminToken}
                  onChange={(event) => {
                    setAdminToken(event.target.value)
                    setTokenSaved(false)
                  }}
                  placeholder="Enter your Render admin token"
                  autoComplete="new-password"
                />
              </label>

              <div className="filter-footer">
                <span>
                  {tokenSaved
                    ? 'Token saved for this browser session.'
                    : 'Token not saved for this session.'}
                </span>

                <div>
                  <button
                    type="button"
                    className="button button-quiet"
                    onClick={clearAdminToken}
                  >
                    Clear token
                  </button>

                  <button
                    type="button"
                    className="button button-primary"
                    onClick={saveAdminToken}
                  >
                    Save admin token
                  </button>
                </div>
              </div>

              <div className="metadata-note">
                <ShieldCheck size={17} />
                <span>
                  The token is stored in this browser session, not in the
                  project source code. Use this only on a trusted device.
                </span>
              </div>
            </section>

            <section className="panel">
              <SectionHeading
                eyebrow="AUTOMATION"
                title="Automatic collection schedule"
              />

              <div className="automation-overview">
                <div className="automation-status-block">
                  <span className="status-badge success">
                    <i />
                    GitHub Actions schedule configured
                  </span>

                  <strong>Automatic collection every 2 hours</strong>

                  <p>
                    GitHub Actions is configured to trigger the collection
                    workflow every 2 hours, giving 12 scheduled runs per day.
                    This schedule operates independently of the backend
                    scheduler.
                  </p>
                </div>

                <div className="automation-config">
                  <div>
                    <span>Configured feeds</span>
                    <strong>
                      {systemStatus
                        ? formatNumber(systemStatus.configured_feed_count)
                        : '—'}
                    </strong>
                  </div>

                  <div>
                    <span>Collection interval</span>
                    <strong>Every 2 hours</strong>
                  </div>

                  <div>
                    <span>Scheduled runs per day</span>
                    <strong>12</strong>
                  </div>

                  <div>
                    <span>Schedule source</span>
                    <strong>GitHub Actions workflow</strong>
                  </div>

                  <div>
                    <span>Backend scheduler</span>
                    <strong>
                      {systemStatus?.scheduler_running ? 'Running' : 'Stopped'}
                    </strong>
                  </div>
                </div>
              </div>

              <div className="metadata-note">
                <ShieldCheck size={17} />
                <span>
                  The GitHub Actions workflow is configured independently of
                  the backend scheduler. The backend scheduler status above
                  reports only the backend process; it does not determine
                  whether GitHub Actions is scheduled. Collection history
                  does not identify whether an individual run was triggered
                  manually or by GitHub Actions.
                </span>
              </div>

              <div className="automation-latest-run">
                <SectionHeading
                  eyebrow="LATEST RECORDED EXECUTION"
                  title="Collection run details"
                />

                {history.length > 0 ? (
                  <div className="automation-config">
                    <div>
                      <span>Run ID</span>
                      <strong>#{history[0].id}</strong>
                    </div>

                    <div>
                      <span>Status</span>
                      <strong>
                        {String(history[0].status || 'Unknown').replaceAll(
                          '_',
                          ' ',
                        )}
                      </strong>
                    </div>

                    <div>
                      <span>Retrieved</span>
                      <strong>{formatNumber(history[0].retrieved)}</strong>
                    </div>

                    <div>
                      <span>New articles inserted</span>
                      <strong>{formatNumber(history[0].inserted)}</strong>
                    </div>

                    <div>
                      <span>Duplicates skipped</span>
                      <strong>{formatNumber(history[0].duplicates)}</strong>
                    </div>

                    <div>
                      <span>Started</span>
                      <strong>{formatDate(history[0].started_at, true)}</strong>
                    </div>
                  </div>
                ) : (
                  <p className="subtle-help">
                    No collection execution has been recorded yet.
                  </p>
                )}
              </div>

              <div className="metadata-note">
                <ShieldCheck size={17} />
                <span>
                  News retention is configured for 7 days by the backend.
                  Automatic cleanup execution has not been verified, so do
                  not assume old records are being deleted automatically.
                </span>
              </div>
            </section>

            <section className="panel">
              <SectionHeading
                eyebrow="CONFIGURED RSS / ATOM FEEDS"
                title="News source health"
              />
              <SourcePanel sources={sources} />
            </section>
          </section>
        )}

        {activePage === 'agents' && (
          <AgentMonitoringPage agents={agents} loading={loading} />
        )}

        {activePage === 'history' && (
          <CollectionHistoryPage history={history} loading={loading} />
        )}

        <footer className="app-footer">
          <span>
            INFORVEX <b>•</b> Multi-Agent News Management System
          </span>
          <span>Data shown from your configured backend sources</span>
        </footer>
      </main>
    </div>
  )
}

export default App
