<script lang="ts">
  import LiveBadge from "$lib/items/LiveBadge.svelte";
  import SentimentTracker from "$lib/items/SentimentTracker.svelte";
  import TimelineEvent from "$lib/items/TimelineEvent.svelte";
  import { ArrowLeft, Bookmark, Ellipsis, Share } from "lucide-svelte";

  interface Props {
    title?: string;
    onBack?: () => void;
  }

  let { title = "Topic Timeline", onBack }: Props = $props();

  type TimeInterval = "1min" | "5min" | "1hour";
  let selectedInterval = $state<TimeInterval>("1min");
</script>

<nav class="flex flex-col gap-y-2 pb-2">
  <div class="flex items-center gap-x-4 justify-between">
    <div>
      {#if onBack}
        <button onclick={onBack}>
          <ArrowLeft size={32} class="hover:bg-stone-800 rounded-full p-1" />
        </button>
      {/if}
    </div>
    <div class="flex flex-row gap-x-2 items-center">
      <button>
        <Share size={32} class="hover:bg-stone-800 rounded-full p-1" />
      </button>
      <button>
        <Bookmark size={32} class="hover:bg-stone-800 rounded-full p-1" />
      </button>
      <button>
        <Ellipsis size={32} class="hover:bg-stone-800 rounded-full p-1" />
      </button>
    </div>
  </div>
  <div class="flex flex-row gap-x-3 align-text-bottom">
    <h1 class="font-bold text-2xl">{title}</h1>
    <LiveBadge />
  </div>
  <p class="">
    Live updates and analysis for this trending topic. Follow along as events
    unfold in real-time with AI-powered insights from Grok.
  </p>
  <SentimentTracker />
  <div class="flex flex-row gap-x-2 align-center">
    <img src="/grok.svg" class="text-stone-800 w-5 h-5" alt="Grok" />
    <p class="text-stone-500 text-sm">Continuously updated with Grok</p>
  </div>
</nav>
<div class="border-y border-y-stone-800 -mx-4">
  <button
    onclick={() => (selectedInterval = "1min")}
    class="hover:bg-stone-800 rounded-top-xl py-2 px-4 font-bold {selectedInterval ===
    '1min'
      ? 'active'
      : ''}"
  >
    Every minute
  </button>
  <button
    onclick={() => (selectedInterval = "5min")}
    class="hover:bg-stone-800 rounded-top-xl py-2 px-4 font-bold {selectedInterval ===
    '5min'
      ? 'active'
      : ''}"
  >
    5 Minutes
  </button>
  <button
    onclick={() => (selectedInterval = "1hour")}
    class="hover:bg-stone-800 rounded-top-xl py-2 px-4 font-bold {selectedInterval ===
    '1hour'
      ? 'active'
      : ''}"
  >
    1 hour
  </button>
</div>

<div class="flex flex-col py-2">
  {#each Array(5) as _, i}
    <TimelineEvent
      content="Timeline event {i + 1} for {title}"
      isLast={i === 4}
    />
  {/each}
  <TimelineEvent timestamp="Notable Tweet" content="" isLast={true} />
</div>

<style>
  button.active {
    border-bottom: 2px solid rgb(59, 130, 246);
  }
</style>
