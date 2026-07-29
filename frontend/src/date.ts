const formatter = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false
});

export function formatDateTime(value: string): string {
  return formatter.format(new Date(value)).replace(/\//g, ".");
}

export function defaultLocalStart(): string {
  const date = new Date(Date.now() + 60 * 60 * 1000);
  date.setMinutes(Math.ceil(date.getMinutes() / 15) * 15, 0, 0);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function toLocalInputValue(value: string): string {
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function durationText(start: string, end: string): string {
  const minutes = Math.round(
    (new Date(end).getTime() - new Date(start).getTime()) / 60_000
  );
  return minutes >= 60 && minutes % 60 === 0
    ? `${minutes / 60} 小时`
    : `${minutes} 分钟`;
}
