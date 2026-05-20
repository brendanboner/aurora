/**
 * A1LogoMark — Agent ONE gradient logo mark, standalone React component.
 *
 * Ported from OCTO-NOVA2: apps/web/src/components/A1Logo.tsx + svgPaths.ts
 * No external dependencies. Accepts a `size` prop (height in px, default 34).
 *
 * The logo is composed of three overlapping SVG groups, each with its own
 * linear gradient, producing the blue → violet → fuchsia Agent One identity.
 */
import React from 'react';

const NATIVE_W = 136;
const NATIVE_H = 126;

function A1LogoSVG() {
  return (
    <svg
      viewBox={`0 0 ${NATIVE_W} ${NATIVE_H}`}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      width={NATIVE_W}
      height={NATIVE_H}
      aria-label="Agent One Logo"
      role="img"
    >
      <defs>
        {/* Group 3 — gradient 1 (upper-left wing) */}
        <linearGradient id="a1g-p0" gradientUnits="userSpaceOnUse" x1="93.2801" y1="3.84639" x2="38.9091" y2="60.4576">
          <stop offset="0.43" stopColor="#6C1AC7" stopOpacity="0" />
          <stop offset="0.61" stopColor="#4D28C1" stopOpacity="0.37" />
          <stop offset="0.79" stopColor="#3136BC" stopOpacity="0.71" />
          <stop offset="0.93" stopColor="#1F3EB9" stopOpacity="0.92" />
          <stop offset="1"    stopColor="#1942B8" />
        </linearGradient>
        <linearGradient id="a1g-p1" gradientUnits="userSpaceOnUse" x1="-8.62515" y1="75.8452" x2="77.6445" y2="64.4251">
          <stop offset="0.17" stopColor="#3E34DC" />
          <stop offset="0.44" stopColor="#345FE4" />
          <stop offset="0.75" stopColor="#2A8BED" />
          <stop offset="0.91" stopColor="#279DF1" />
        </linearGradient>

        {/* Group 2 — gradient 2 (right wing) */}
        <linearGradient id="a1g-p2" gradientUnits="userSpaceOnUse" x1="-2.96651" y1="38.4209" x2="93.7012" y2="43.5263">
          <stop offset="0.257268" stopColor="#180764" stopOpacity="0" />
          <stop offset="0.52"     stopColor="#850E9B" />
          <stop offset="0.95"     stopColor="#F427C8" />
        </linearGradient>
        <linearGradient id="a1g-p3" gradientUnits="userSpaceOnUse" x1="114.718" y1="86.9941" x2="46.5529" y2="1.16604">
          <stop offset="0.365385" stopColor="#F428C8" />
          <stop offset="0.61"     stopColor="#B549D6" />
          <stop offset="0.8"      stopColor="#6E70E6" />
          <stop offset="0.93"     stopColor="#4288F1" />
          <stop offset="1"        stopColor="#3F9EFF" />
        </linearGradient>

        {/* Group 1 — gradient 3 (central body) */}
        <linearGradient id="a1g-p4" gradientUnits="userSpaceOnUse" x1="53.1105" y1="84.212" x2="26.8381" y2="40.5033">
          <stop offset="0"    stopColor="#6C1AC7" stopOpacity="0" />
          <stop offset="0.72" stopColor="#6C1AC7" />
          <stop offset="0.73" stopColor="#6E1BC9" />
          <stop offset="0.9"  stopColor="#953CEF" />
          <stop offset="0.99" stopColor="#A449FE" />
        </linearGradient>
        <linearGradient id="a1g-p5" gradientUnits="userSpaceOnUse" x1="41.2438" y1="-7.43922" x2="10.694" y2="74.5413">
          <stop offset="0.47" stopColor="#A548FF" />
          <stop offset="0.64" stopColor="#8153FB" />
          <stop offset="0.88" stopColor="#5562F6" />
          <stop offset="1"    stopColor="#4468F5" />
        </linearGradient>
      </defs>

      {/* Group 3 — upper-left diagonal wing */}
      <g transform="translate(31, 0)">
        <path
          d="M13.8662 59.1414C6.20812 60.3069 0.943065 67.4529 2.10639 75.1025C3.26972 82.7521 10.4209 88.0086 18.079 86.8432L57.6681 80.8185C65.3262 79.6531 70.5913 72.5071 69.428 64.8575C68.2646 57.2078 61.1134 51.9513 53.4553 53.1167L13.8662 59.1414Z"
          fill="url(#a1g-p0)"
        />
        <path
          d="M5.68225 63.2685L49.7923 5.47885C54.4675 -0.662068 63.2082 -1.80078 69.347 2.87607C75.4859 7.55293 76.6242 16.2966 71.9489 22.4375L48.2474 53.4675L53.0853 52.8168C60.7283 51.8001 67.7209 57.1683 68.7779 64.8139C69.7942 72.4596 64.4279 79.4545 56.7848 80.5119L18.5697 85.6361C12.9594 86.3681 7.47104 83.684 4.66589 78.8038C1.82008 73.9236 2.22662 67.8234 5.64159 63.3092L5.68225 63.2685Z"
          fill="url(#a1g-p1)"
        />
      </g>

      {/* Group 2 — right curved wing */}
      <g transform="translate(19, 29)">
        <path
          d="M85.0253 64.0133L12.6604 57.2624C4.97675 56.5304 -0.633557 49.7388 0.0575678 42.0931C0.748693 34.4475 7.57863 28.7946 15.2217 29.4859L54.0873 33.1054L50.9569 29.3639C46.0377 23.4264 46.8508 14.642 52.7863 9.72113C58.7219 4.80026 67.5032 5.61363 72.4224 11.5512L97.059 41.2391C100.677 45.5906 101.287 51.6502 98.6445 56.6524C96.002 61.6546 90.6356 64.542 85.0253 64.054V64.0133Z"
          fill="url(#a1g-p2)"
        />
        <path
          d="M75.9363 59.2738C80.9896 65.1468 89.8386 65.8157 95.701 60.7679C101.563 55.7202 102.219 46.8672 97.1659 40.9943L71.0423 10.6339C65.989 4.76095 57.14 4.09201 51.2776 9.13976C45.4152 14.1875 44.7593 23.0405 49.8127 28.9134L75.9363 59.2738Z"
          fill="url(#a1g-p3)"
        />
      </g>

      {/* Group 1 — central body / spine */}
      <g transform="translate(28, 13)">
        <path
          d="M44.9407 13.574L74.6997 79.904C77.8708 86.9397 74.6997 95.1953 67.6665 98.3674C60.6333 101.54 52.3805 98.3674 49.2094 91.3318L33.2322 55.7064L31.4841 60.2612C28.7602 67.4595 20.67 71.079 13.4742 68.3542C6.27837 65.6294 2.66012 57.5365 5.38397 50.3382L19.0845 14.306C21.0766 9.01915 26.0771 5.481 31.728 5.31833C37.379 5.15566 42.5421 8.40912 44.8594 13.574H44.9407Z"
          fill="url(#a1g-p4)"
        />
        <path
          d="M44.75 22.7341C47.3879 15.4484 43.6307 7.4061 36.358 4.7711C29.0854 2.13609 21.0512 5.90623 18.4133 13.1919L4.77639 50.8559C2.13846 58.1416 5.89566 66.1839 13.1683 68.8189C20.441 71.4539 28.4751 67.6838 31.113 60.3981L44.75 22.7341Z"
          fill="url(#a1g-p5)"
        />
      </g>
    </svg>
  );
}

export default function A1LogoMark({ size = 34 }) {
  const scale = size / NATIVE_H;
  const w = Math.round(NATIVE_W * scale);
  const h = Math.round(NATIVE_H * scale);

  return (
    <div
      style={{
        width: w,
        height: h,
        position: 'relative',
        overflow: 'hidden',
        flexShrink: 0,
        display: 'inline-block',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: NATIVE_W,
          height: NATIVE_H,
          transform: `scale(${scale})`,
          transformOrigin: 'top left',
        }}
      >
        <A1LogoSVG />
      </div>
    </div>
  );
}
