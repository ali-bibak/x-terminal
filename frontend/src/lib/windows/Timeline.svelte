<script lang="ts">
  import api from "$lib/api";
  import LiveBadge from "$lib/items/LiveBadge.svelte";
  import SentimentTracker from "$lib/items/SentimentTracker.svelte";
  import TimelineEvent from "$lib/items/TimelineEvent.svelte";
  import {
    nullopt,
    type BarResponse,
    type Optional,
    type TopicResponse,
  } from "$lib/types";
  import { ArrowLeft, Bookmark, Ellipsis, Share } from "lucide-svelte";
  import { onMount } from "svelte";

  interface Props {
    id: string;
    title?: string;
    onBack?: () => void;
  }

  let { title = "Topic Timeline", onBack, id }: Props = $props();

  let topicInfo: Optional<TopicResponse> = $state(nullopt);
  let barsInfo: BarResponse[] = $state([]);

  async function getTopicInfo() {
    topicInfo = await api.getTopic(id);
  }

  async function getBarsInfo() {
    barsInfo = (await api.getBars(id, selectedInterval)).filter(
      (b) => b.post_count > 0,
    );
  }

  async function getLatestBars() {
    const newBar = await api.getLatestBar(id);
    if (
      barsInfo.length > 0 &&
      newBar.end !== barsInfo[0].end &&
      newBar.post_count > 0
    ) {
      barsInfo = [newBar, ...barsInfo];
    }
  }

  onMount(() => {
    getTopicInfo();
    getBarsInfo();

    const free = setInterval(getLatestBars, 10000);

    return () => {
      clearInterval(free);
    };
  });

  const TIME_INTERVALS = [
    { value: "15s", label: "15s" },
    { value: "30s", label: "30s" },
    { value: "1m", label: "1m" },
    { value: "5m", label: "5m" },
    { value: "15m", label: "15m" },
    { value: "30m", label: "30m" },
    { value: "1h", label: "1h" },
  ] as const;

  type TimeInterval = (typeof TIME_INTERVALS)[number]["value"];
  let selectedInterval = $state<TimeInterval>("1m");
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
  <SentimentTracker
    data={barsInfo.map((bar) => parseFloat(bar.sentiment as string))}
  />
  <div class="flex flex-row gap-x-2 align-center">
    <img src="/grok.svg" class="text-stone-800 w-5 h-5" alt="Grok" />
    <p class="text-stone-500 text-sm">Continuously updated with Grok</p>
  </div>
</nav>
<div class="border-y border-y-stone-800 -mx-4">
  {#each TIME_INTERVALS as interval}
    <button
      onclick={() => {
        selectedInterval = interval.value;
        barsInfo = [];
        getBarsInfo();
      }}
      class="hover:bg-stone-800 rounded-top-xl py-2 px-4 font-bold {selectedInterval ===
      interval.value
        ? 'active'
        : ''}"
    >
      {interval.label}
    </button>
  {/each}
</div>

<div class="flex flex-col py-2">
  {#each barsInfo as bars, i}
    <TimelineEvent content={bars} isLast={i === barsInfo.length - 1} />
  {/each}
  {#if barsInfo.length === 0}
    <h1 class="font-bold text-3xl mt-5">Waiting for posts...</h1>
    <p>It's empty now, but it won't be for long.</p>
  {/if}
</div>

<style>
  button.active {
    border-bottom: 2px solid rgb(59, 130, 246);
  }
</style>
