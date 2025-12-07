<script lang="ts">
  interface Props {
    data?: number[]; // Sentiment values from -1 (negative) to 1 (positive)
  }

  let { data = [] }: Props = $props();
  let selected: "SENTIMENT" | "VOLUME" = "SENTIMENT";

  const width = 400;
  const height = 20;
  const padding = 2;

  // Normalize data to SVG coordinates
  function getPoints(): string {
    const chartWidth = width - padding * 2;
    const chartHeight = height - padding * 2;

    return data
      .map((value, index) => {
        const x = padding + (index / (data.length - 1)) * chartWidth;
        // Map -1 to 1 range to height (inverted because SVG Y increases downward)
        const y = padding + chartHeight - ((value + 1) / 2) * chartHeight;
        return `${x},${y}`;
      })
      .join(" ");
  }

  function getColor(value: number): string {
    // Map -1 to 1 to red (0) to green (120) on HSL scale
    const hue = ((value + 1) / 2) * 120;
    return `hsl(${hue}, 70%, 50%)`;
  }
</script>

<div class="w-full">
  <div class="flex items-center justify-between mb-2">
    {#if selected === "SENTIMENT"}
      <h3 class="text-sm font-medium text-stone-400">Sentiment</h3>
      <span class="text-sm" style="color: {getColor(data[data.length - 1])}">
        {data[data.length - 1] > 0
          ? "Positive"
          : data[data.length - 1] < 0
            ? "Negative"
            : "Neutral"}
      </span>
    {:else if selected === "VOLUME"}
      <h3 class="text-sm font-medium text-stone-400">Volume</h3>
    {/if}
  </div>

  <svg
    viewBox="0 0 {width} {height}"
    class="w-full bg-black"
    preserveAspectRatio="none"
  >
    <defs>
      <linearGradient id="lineGradient" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" style="stop-color:rgb(34,197,94);stop-opacity:1" />
        <stop offset="50%" style="stop-color:rgb(161,161,170);stop-opacity:1" />
        <stop offset="100%" style="stop-color:rgb(239,68,68);stop-opacity:1" />
      </linearGradient>
    </defs>

    <!-- Center line (neutral) -->
    <line
      x1={padding}
      y1={height / 2}
      x2={width - padding}
      y2={height / 2}
      stroke="rgb(82, 82, 91)"
      stroke-width="1"
      stroke-dasharray="4,4"
      opacity="0.5"
    />

    <!-- Line segments with individual colors -->
    {#each data as value, index}
      {#if index < data.length - 1}
        {@const chartWidth = width - padding * 2}
        {@const chartHeight = height - padding * 2}
        {@const x1 = padding + (index / (data.length - 1)) * chartWidth}
        {@const y1 = padding + chartHeight - ((value + 1) / 2) * chartHeight}
        {@const x2 = padding + ((index + 1) / (data.length - 1)) * chartWidth}
        {@const y2 =
          padding + chartHeight - ((data[index + 1] + 1) / 2) * chartHeight}
        {@const avgValue = (value + data[index + 1]) / 2}
        <line
          {x1}
          {y1}
          {x2}
          {y2}
          stroke={getColor(avgValue)}
          stroke-width="2.5"
          stroke-linecap="round"
        />
      {/if}
    {/each}
  </svg>
</div>
