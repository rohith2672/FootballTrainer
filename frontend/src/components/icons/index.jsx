// Small inline SVG icons. All are decorative (aria-hidden): the surrounding
// control or text carries the accessible name. They inherit currentColor.

function Svg({ size = 20, className = '', children, strokeWidth = 1.8, viewBox = '0 0 24 24' }) {
  return (
    <svg
      viewBox={viewBox}
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={`icon ${className}`.trim()}
    >
      {children}
    </svg>
  );
}

export function StarIcon({ filled = false, size = 20, className = 'star-icon' }) {
  return (
    <Svg size={size} className={className}>
      <path
        d="M12 2.8l2.8 5.9 6.4.8-4.7 4.4 1.2 6.4L12 17.2l-5.7 3.1 1.2-6.4-4.7-4.4 6.4-.8z"
        fill={filled ? 'currentColor' : 'none'}
      />
    </Svg>
  );
}

export function CalendarIcon(props) {
  return (
    <Svg {...props}>
      <rect x="3.5" y="5" width="17" height="15.5" rx="2.5" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </Svg>
  );
}

export function GlobeIcon(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17M12 3.5c2.4 2.4 3.6 5.2 3.6 8.5s-1.2 6.1-3.6 8.5c-2.4-2.4-3.6-5.2-3.6-8.5s1.2-6.1 3.6-8.5z" />
    </Svg>
  );
}

export function ChartIcon(props) {
  return (
    <Svg {...props}>
      <path d="M4 4v16h16" />
      <path d="M7.5 15l3.5-4 3 2.5 4.5-6" />
    </Svg>
  );
}

export function NewsIcon(props) {
  return (
    <Svg {...props}>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M7 9h10M7 12.5h10M7 16h6" />
    </Svg>
  );
}

export function AlertIcon(props) {
  return (
    <Svg {...props}>
      <path d="M12 3.5l9 16H3z" />
      <path d="M12 10v4.5M12 17.2v.1" />
    </Svg>
  );
}

export function SearchIcon(props) {
  return (
    <Svg {...props}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M15.5 15.5l5 5" />
    </Svg>
  );
}

export function InboxIcon(props) {
  return (
    <Svg {...props}>
      <path d="M3.5 13.5l2.6-8h11.8l2.6 8v5h-17z" />
      <path d="M3.5 13.5h5l1.5 2.5h4l1.5-2.5h5" />
    </Svg>
  );
}

export function CheckIcon(props) {
  return (
    <Svg strokeWidth={2.4} {...props}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </Svg>
  );
}

export function CrossIcon(props) {
  return (
    <Svg strokeWidth={2.4} {...props}>
      <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />
    </Svg>
  );
}

export function ChevronDownIcon({ up = false, className = '', ...props }) {
  return (
    <Svg strokeWidth={2.2} className={`chevron ${up ? 'up' : ''} ${className}`.trim()} {...props}>
      <path d="M6.5 9.5l5.5 5.5 5.5-5.5" />
    </Svg>
  );
}

export function SunIcon(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7" />
    </Svg>
  );
}

export function MoonIcon(props) {
  return (
    <Svg {...props}>
      <path d="M19.5 14.6A8 8 0 019.4 4.5a8 8 0 1010.1 10.1z" />
    </Svg>
  );
}

export function MonitorIcon(props) {
  return (
    <Svg {...props}>
      <rect x="3" y="4.5" width="18" height="12" rx="2" />
      <path d="M9 20h6M12 16.5V20" />
    </Svg>
  );
}

/** Football: the brand mark (outline ball with a centre panel). */
export function BallIcon(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8.2l3.6 2.6-1.4 4.2H9.8l-1.4-4.2z" fill="currentColor" />
      <path d="M12 8.2V3.2M15.6 10.8l4.6-1.6M14.2 15l2.9 4M9.8 15l-2.9 4M8.4 10.8L3.8 9.2" />
    </Svg>
  );
}
