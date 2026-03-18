import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './Events.css';
import {
  CalendarIcon,
  CheckIcon,
  LinkIcon,
  MapPinIcon,
  DocumentIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from '../components/icons';

const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const WORKGROUP_PATTERN = /\b(?:wg|tg|sg|ig|cg|rg|working\s+group|task\s+group|study\s+group|interest\s+group|research\s+group)\b/i;
const WORKGROUP_STOPWORDS = new Set([
  'WI',
  'WI-FI',
  'WIFI',
  'ALLIANCE',
  'WORKING',
  'WORKGROUP',
  'GROUP',
  'TASK',
  'STUDY',
  'INTEREST',
  'RESEARCH',
  'THE',
  'AND',
  'FOR',
  'OF',
]);

const getMonthStart = (value = new Date()) => new Date(value.getFullYear(), value.getMonth(), 1);

const addMonths = (date, amount) => new Date(date.getFullYear(), date.getMonth() + amount, 1);

const formatKeyDate = (date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const getCalendarStart = (monthDate) => {
  const start = getMonthStart(monthDate);
  const jsDay = start.getDay();
  const mondayOffset = (jsDay + 6) % 7;
  start.setDate(start.getDate() - mondayOffset);
  return start;
};

const normalizeEventDate = (value) => {
  if (!value) {
    return null;
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }

  return parsed;
};

const getEventTypeClass = (eventType) => {
  const normalized = (eventType || '').toLowerCase();
  if (normalized.includes('webinar')) return 'type-webinar';
  if (normalized.includes('conference')) return 'type-conference';
  if (normalized.includes('plenary')) return 'type-plenary';
  if (normalized.includes('summit')) return 'type-summit';
  if (normalized.includes('workshop')) return 'type-workshop';
  if (normalized.includes('task')) return 'type-task-group';
  if (normalized.includes('meeting')) return 'type-meeting';
  return 'type-default';
};

const extractWorkgroupInitials = (sourceLabel) => {
  if (!sourceLabel) {
    return '';
  }

  const acronymMatches = sourceLabel.match(/\b[A-Z0-9]{2,5}\b/g);
  if (acronymMatches?.length) {
    return acronymMatches[acronymMatches.length - 1].slice(0, 4);
  }

  const pieces = sourceLabel
    .replace(/Wi-Fi/gi, 'WIFI')
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((token) => token.toUpperCase())
    .filter((token) => !WORKGROUP_STOPWORDS.has(token));

  const compact = pieces.map((token) => (/^\d+$/.test(token) ? token : token[0])).join('');
  return compact.slice(0, 4) || sourceLabel.replace(/[^A-Za-z0-9]/g, '').slice(0, 4).toUpperCase();
};

const formatMonthLabel = (date) =>
  date.toLocaleDateString('en-US', {
    month: 'long',
    year: 'numeric',
  });

const formatDayLabel = (date) =>
  date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  });

const formatMonthValue = (date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  return `${year}-${month}`;
};

const isSameMonth = (left, right) =>
  left.getFullYear() === right.getFullYear() && left.getMonth() === right.getMonth();

const formatMonthChipLabel = (date) =>
  date.toLocaleDateString('en-US', {
    month: 'short',
  });

const getSafeTimeZone = (timeZone) => {
  if (!timeZone) {
    return null;
  }

  try {
    Intl.DateTimeFormat('en-US', { timeZone }).format(new Date());
    return timeZone;
  } catch (_error) {
    return null;
  }
};

const formatEventTime = (value, timeZone) => {
  const date = normalizeEventDate(value);
  if (!date) {
    return 'TBD';
  }

  const formatterOptions = {
    hour: 'numeric',
    minute: '2-digit',
  };

  const safeTimeZone = getSafeTimeZone(timeZone);
  if (safeTimeZone) {
    formatterOptions.timeZone = safeTimeZone;
    formatterOptions.timeZoneName = 'short';
  }

  return new Intl.DateTimeFormat('en-US', formatterOptions).format(date);
};

const formatDateRange = (startDate, endDate) => {
  const start = normalizeEventDate(startDate);
  const end = normalizeEventDate(endDate);

  if (!start) {
    return 'TBD';
  }

  const startLabel = formatDayLabel(start);
  if (!end) {
    return startLabel;
  }

  const sameDay = formatKeyDate(start) === formatKeyDate(end);
  return sameDay ? startLabel : `${startLabel} - ${formatDayLabel(end)}`;
};

const formatTickerDate = (value) => {
  const date = normalizeEventDate(value);
  if (!date) {
    return 'Date TBD';
  }

  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
};

const Events = () => {
  const navigate = useNavigate();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [availableEventTypes, setAvailableEventTypes] = useState([]);
  const [availableDatasources, setAvailableDatasources] = useState([]);
  const [eventType, setEventType] = useState('');
  const [currentMonth, setCurrentMonth] = useState(getMonthStart());
  const [conferenceTickerIndex, setConferenceTickerIndex] = useState(0);

  const fetchFilterOptions = useCallback(async () => {
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch('/api/backend/events/metadata/filters', {
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setAvailableEventTypes(data.event_types || []);
        setAvailableDatasources(data.datasources || []);
      }
    } catch (err) {
      console.error('Error fetching event filter options:', err);
    }
  }, []);

  const fetchEvents = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const params = new URLSearchParams();
      if (eventType) params.append('event_type', eventType);
      params.append('sort_by', 'start_date');
      params.append('sort_order', 'asc');
      params.append('limit', '500');

      const token = localStorage.getItem('auth_token');
      const response = await fetch(`/api/backend/events?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch events');
      }

      const data = await response.json();
      setEvents(data.events || []);
    } catch (err) {
      console.error('Error fetching events:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [eventType]);

  useEffect(() => {
    fetchFilterOptions();
  }, [fetchFilterOptions]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  const handleEventClick = (urlHash) => {
    navigate(`/events/${urlHash}`);
  };

  const handleExternalLink = (e, url) => {
    e.stopPropagation();
    window.open(url, '_blank', 'noopener,noreferrer');
  };

  const datasourceNameMap = useMemo(() => {
    const map = {};
    availableDatasources.forEach((ds) => {
      map[ds.datasource_id] = ds.name;
    });
    return map;
  }, [availableDatasources]);

  const calendarEvents = useMemo(
    () =>
      events
        .filter((event) => event.status !== 'cancelled')
        .map((event) => ({
          ...event,
          startDateObject: normalizeEventDate(event.start_date),
          sourceLabel: datasourceNameMap[event.datasource_id] || event.datasource_id || '',
        }))
        .filter((event) => event.startDateObject)
        .sort((left, right) => left.startDateObject - right.startDateObject),
    [datasourceNameMap, events]
  );

  const eventsByDay = useMemo(() => {
    const grouped = {};
    calendarEvents.forEach((event) => {
      const key = formatKeyDate(event.startDateObject);
      if (!grouped[key]) {
        grouped[key] = [];
      }
      grouped[key].push(event);
    });
    return grouped;
  }, [calendarEvents]);

  const monthEvents = useMemo(
    () =>
      calendarEvents.filter(
        (event) =>
          event.startDateObject.getFullYear() === currentMonth.getFullYear() &&
          event.startDateObject.getMonth() === currentMonth.getMonth()
      ),
    [calendarEvents, currentMonth]
  );

  const calendarDays = useMemo(() => {
    const start = getCalendarStart(currentMonth);
    return Array.from({ length: 42 }, (_, index) => {
      const date = new Date(start);
      date.setDate(start.getDate() + index);
      return {
        date,
        key: formatKeyDate(date),
        isCurrentMonth: date.getMonth() === currentMonth.getMonth(),
        isToday: formatKeyDate(date) === formatKeyDate(new Date()),
      };
    });
  }, [currentMonth]);

  const monthLegend = useMemo(() => {
    const seen = new Set();
    return monthEvents
      .map((event) => event.event_type)
      .filter(Boolean)
      .filter((type) => {
        const key = type.toLowerCase();
        if (seen.has(key)) {
          return false;
        }
        seen.add(key);
        return true;
      })
      .slice(0, 6);
  }, [monthEvents]);

  const selectableMonths = useMemo(() => {
    const monthMap = new Map();

    calendarEvents.forEach((event) => {
      const monthDate = getMonthStart(event.startDateObject);
      monthMap.set(formatMonthValue(monthDate), monthDate);
    });

    if (!monthMap.has(formatMonthValue(currentMonth))) {
      monthMap.set(formatMonthValue(currentMonth), currentMonth);
    }

    return Array.from(monthMap.values()).sort((left, right) => left - right);
  }, [calendarEvents, currentMonth]);

  const visibleMonthOptions = useMemo(() => {
    const currentIndex = selectableMonths.findIndex((monthDate) => isSameMonth(monthDate, currentMonth));
    if (currentIndex === -1) {
      return selectableMonths.slice(0, 5);
    }

    const start = Math.max(0, currentIndex - 2);
    const end = Math.min(selectableMonths.length, start + 5);
    return selectableMonths.slice(Math.max(0, end - 5), end);
  }, [currentMonth, selectableMonths]);

  const upcomingConferences = useMemo(() => {
    const now = new Date();
    const nextYear = new Date(now);
    nextYear.setFullYear(nextYear.getFullYear() + 1);

    return calendarEvents.filter((event) => {
      const eventTypeValue = (event.event_type || '').toLowerCase();
      return (
        eventTypeValue.includes('conference') &&
        event.startDateObject >= now &&
        event.startDateObject <= nextYear
      );
    });
  }, [calendarEvents]);

  useEffect(() => {
    setConferenceTickerIndex(0);
  }, [upcomingConferences.length]);

  useEffect(() => {
    if (upcomingConferences.length <= 1) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      setConferenceTickerIndex((current) => (current + 1) % upcomingConferences.length);
    }, 4000);

    return () => window.clearInterval(intervalId);
  }, [upcomingConferences]);

  const activeConferenceTickerItem =
    upcomingConferences.length > 0
      ? upcomingConferences[conferenceTickerIndex % upcomingConferences.length]
      : null;

  if (loading && events.length === 0) {
    return (
      <div className="events-container">
        <div className="events-header">
          <h1><CalendarIcon size={32} /> Events</h1>
        </div>
        <div className="loading-message">Loading events…</div>
      </div>
    );
  }

  return (
    <div className="events-container">
      <div className="events-header">
        <div className="events-header-main">
          <h1><CalendarIcon size={32} /> Events</h1>
          <div className="events-header-subrow">
            <p className="events-subtitle">
              A monthly view of meetings, workshops, webinars, and conferences across the ecosystem.
            </p>
            <div className="filter-group calendar-type-filter header-type-filter">
              <select value={eventType} onChange={(e) => setEventType(e.target.value)}>
                <option value="">All types</option>
                {availableEventTypes.map((et) => (
                  <option key={et.type} value={et.type}>
                    {et.type.charAt(0).toUpperCase() + et.type.slice(1)} ({et.count})
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      </div>

      {error && <div className="error-message">Error loading events: {error}</div>}

      {activeConferenceTickerItem && (
        <div className="conference-ticker" role="status" aria-live="polite">
          <span className="conference-ticker-label">Conference watch</span>
          <button
            type="button"
            className="conference-ticker-content"
            onClick={() => handleEventClick(activeConferenceTickerItem.url_hash)}
          >
            <span className="conference-ticker-dot" />
            <span className="conference-ticker-text">
              <strong>{activeConferenceTickerItem.name}</strong>
              <span className="conference-ticker-separator">•</span>
              <span>{formatTickerDate(activeConferenceTickerItem.start_date)}</span>
              {activeConferenceTickerItem.location && (
                <>
                  <span className="conference-ticker-separator">•</span>
                  <span>{activeConferenceTickerItem.location}</span>
                </>
              )}
              {activeConferenceTickerItem.sourceLabel && (
                <>
                  <span className="conference-ticker-separator">•</span>
                  <span>{activeConferenceTickerItem.sourceLabel}</span>
                </>
              )}
              {upcomingConferences.length > 1 && (
                <>
                  <span className="conference-ticker-separator">•</span>
                  <span>
                    {conferenceTickerIndex + 1} / {upcomingConferences.length}
                  </span>
                </>
              )}
            </span>
          </button>
        </div>
      )}

      <div className="calendar-toolbar">
        <div className="calendar-toolbar-left">
          {monthLegend.length > 0 && (
            <div className="calendar-legend calendar-legend-inline">
              {monthLegend.map((type) => (
                <div key={type} className="calendar-legend-item">
                  <span className={`legend-dot ${getEventTypeClass(type)}`} />
                  <span>{type}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="calendar-toolbar-center">
          <div className="calendar-nav">
            <button
              type="button"
              className="calendar-nav-button"
              onClick={() => setCurrentMonth((prev) => addMonths(prev, -1))}
              aria-label="Previous month"
            >
              <ChevronLeftIcon size={18} />
            </button>
            <div className="calendar-month-strip">
              {visibleMonthOptions.map((monthDate) => (
                <button
                  key={formatMonthValue(monthDate)}
                  type="button"
                  className={`calendar-month-chip ${isSameMonth(monthDate, currentMonth) ? 'active' : ''}`}
                  onClick={() => setCurrentMonth(monthDate)}
                  aria-label={`Show ${formatMonthLabel(monthDate)}`}
                >
                  {formatMonthChipLabel(monthDate)}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="calendar-nav-button"
              onClick={() => setCurrentMonth((prev) => addMonths(prev, 1))}
              aria-label="Next month"
            >
              <ChevronRightIcon size={18} />
            </button>
          </div>
        </div>

        <div className="calendar-toolbar-right">
          <div className="calendar-month-summary">
            {monthEvents.length} event{monthEvents.length === 1 ? '' : 's'}
          </div>
          <button
            type="button"
            className="calendar-today-button"
            onClick={() => setCurrentMonth(getMonthStart())}
          >
            Today
          </button>
        </div>
      </div>

      <div className="calendar-shell">
        <div className="calendar-weekdays">
          {WEEKDAY_LABELS.map((label) => (
            <div key={label} className="calendar-weekday">{label}</div>
          ))}
        </div>

        <div className="calendar-grid">
          {calendarDays.map(({ date, key, isCurrentMonth, isToday }) => {
            const dayEvents = eventsByDay[key] || [];
            const visibleEvents = dayEvents.slice(0, 3);
            const hiddenCount = dayEvents.length - visibleEvents.length;

            return (
              <div
                key={key}
                className={[
                  'calendar-day',
                  isCurrentMonth ? 'current-month' : 'outside-month',
                  isToday ? 'today' : '',
                ].filter(Boolean).join(' ')}
              >
                <div className="calendar-day-header">
                  <span className="calendar-day-number">{date.getDate()}</span>
                </div>

                <div className="calendar-day-events">
                  {visibleEvents.map((event) => {
                    const sourceLabel = event.sourceLabel;
                    const workgroupInitials = WORKGROUP_PATTERN.test(sourceLabel)
                      ? extractWorkgroupInitials(sourceLabel)
                      : '';

                    return (
                      <button
                        type="button"
                        key={event.url_hash}
                        className={`calendar-event-card ${getEventTypeClass(event.event_type)}`}
                        onClick={() => handleEventClick(event.url_hash)}
                      >
                        <div className="calendar-event-topline">
                          <span className="calendar-event-time">
                            {formatEventTime(event.start_date, event.timezone)}
                          </span>
                          <span className="calendar-event-type">{event.event_type || 'meeting'}</span>
                        </div>

                        <div className="calendar-event-title-row">
                          {workgroupInitials && (
                            <span className="calendar-workgroup-badge" title={sourceLabel}>
                              {workgroupInitials}
                            </span>
                          )}
                          <span className="calendar-event-title">{event.name}</span>
                        </div>

                        <div className="calendar-event-meta">
                          {event.url ? (
                            <span
                              className="calendar-event-inline calendar-event-link"
                              onClick={(e) => handleExternalLink(e, event.url)}
                              role="button"
                              tabIndex={0}
                              title="Open event link"
                              aria-label="Open event link"
                            >
                              <LinkIcon size={12} />
                            </span>
                          ) : event.location ? (
                            <span className="calendar-event-inline">
                              <MapPinIcon size={12} />
                              {event.location}
                            </span>
                          ) : event.document_count > 0 ? (
                            <span className="calendar-event-inline">
                              <DocumentIcon size={12} />
                              {event.document_count} docs
                            </span>
                          ) : null}
                        </div>
                      </button>
                    );
                  })}

                  {hiddenCount > 0 && (
                    <div className="calendar-more-events">+{hiddenCount} more</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {monthEvents.length === 0 && (
        <div className="no-events calendar-no-events">
          <CalendarIcon size={48} color="#999" />
          <p>No events found for {formatMonthLabel(currentMonth)}.</p>
        </div>
      )}

      <div className="events-month-footer">
        <div className="events-month-footer-item">
          <CheckIcon size={16} />
          <span>
            Showing {monthEvents.length} events in {formatMonthLabel(currentMonth)}.
          </span>
        </div>
        {monthEvents[0] && (
          <div className="events-month-footer-item subtle">
            <span>Range: {formatDateRange(monthEvents[0].start_date, monthEvents[monthEvents.length - 1]?.end_date)}</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default Events;
