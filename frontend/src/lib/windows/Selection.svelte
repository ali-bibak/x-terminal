<script lang="ts">
  import CreateTopicPopover from "$lib/components/CreateTopicPopover.svelte";
  import { Search } from "lucide-svelte";
  import type { TopicResponse } from "$lib/types";
  import { onMount } from "svelte";
  import api from "$lib/api";
  import TopicSelection from "$lib/items/TopicSelection.svelte";

  interface Props {
    onNavigate?: (topic: string, id: string) => void;
  }

  let { onNavigate }: Props = $props();
  let isPopoverOpen = $state(false);

  let topics: TopicResponse[] = $state([]);

  async function updateTopics() {
    topics = await api.listTopics();
  }

  onMount(() => {
    updateTopics();
  });
</script>

<CreateTopicPopover bind:isOpen={isPopoverOpen} />

<div class="flex flex-row items-center gap-x-2">
  <div class="relative flex-1">
    <Search
      class="absolute left-4 top-1/2 -translate-y-1/2 text-stone-400"
      size={20}
    />
    <input
      type="text"
      placeholder="Search..."
      class="w-full pl-12 pr-4 py-2 border border-stone-800 rounded-full focus:outline-none focus:border-blue-400"
    />
  </div>
  <button
    onclick={() => (isPopoverOpen = true)}
    class="px-4 py-2 bg-blue-400 hover:bg-blue-400/80 text-white rounded-full font-bold"
  >
    Create Topic
  </button>
</div>

<h1 class="font-bold text-xl mt-4">Subscribed</h1>
<div class="mt-2 -mx-4">
  {#each topics as topic}
    <TopicSelection
      title={topic.label}
      tweetCount={topic.tick_count}
      onclick={() => onNavigate?.(topic.label, topic.id)}
    />
  {/each}
</div>

<h1 class="font-bold text-xl mt-4">In Palo Alto, California</h1>
<div class="mt-2 -mx-4">
  <TopicSelection
    title="Elon visits xAI"
    tweetCount={1402}
    onclick={() => onNavigate?.("Elon visits xAI")}
  />
  <TopicSelection
    title="xAI Hackathon"
    tweetCount={240828}
    onclick={() => onNavigate?.("xAI Hackathon")}
  />
  <TopicSelection
    title="San Jose Highway Accidents"
    tweetCount={2402}
    onclick={() => onNavigate?.("xAI Hackathon")}
  />
</div>

<h1 class="font-bold text-xl mt-4">You'd be Interested</h1>
<div class="mt-2 -mx-4">
  <TopicSelection
    title="FSD 14.2 Released"
    tweetCount={3212839}
    onclick={() => onNavigate?.("FSD 14.2 Released")}
  />
  <TopicSelection
    title="$TSLA Earnings Call"
    tweetCount={459300}
    onclick={() => onNavigate?.("$TSLA Earnings Call")}
  />
  <TopicSelection
    title="Tottenham vs Brentford"
    tweetCount={4820}
    onclick={() => onNavigate?.("Tottenham vs Brentford")}
  />
</div>

<h1 class="font-bold text-xl mt-4">Trending</h1>
<div class="mt-2 -mx-4">
  <TopicSelection
    title="The Boys Season 5 Trailer"
    tweetCount={231232}
    onclick={() => onNavigate?.("The Boys Season 5 Trailer")}
  />
</div>

<h1 class="font-bold text-xl mt-4">Requested</h1>
<div class="mt-2 -mx-4">
  <TopicSelection
    title="GTA VI Trailer 3"
    requested={true}
    tweetCount={0}
    onclick={() => {}}
  />
</div>
