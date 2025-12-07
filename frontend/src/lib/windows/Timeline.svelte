<script lang="ts">
  import LiveBadge from "$lib/items/LiveBadge.svelte";
  import { ArrowLeft, Bookmark, Ellipsis, Share } from "lucide-svelte";

  interface Props {
    title?: string;
    onBack?: () => void;
  }

  let { title = "Topic Timeline", onBack }: Props = $props();
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
  <div class="flex flex-row gap-x-2 align-center">
    <img src="/grok.svg" class="text-stone-800 w-5 h-5" alt="Grok" />
    <p class="text-stone-500 text-sm">Continuously updated with Grok</p>
  </div>
</nav>
<div class="border-y border-y-stone-800 -mx-4">
  <button class="hover:bg-stone-800 rounded-top-xl py-2 px-4 font-bold active">
    Every minute
  </button>
  <button class="hover:bg-stone-800 rounded-top-xl py-2 px-4 font-bold">
    5 Minutes
  </button>
  <button class="hover:bg-stone-800 rounded-top-xl py-2 px-4 font-bold">
    1 hour
  </button>
</div>

<div class="flex flex-col py-2">
  {#each Array(5) as _, i}
    <div class="flex gap-x-4">
      <div class="flex flex-col items-center">
        <div class="w-2 h-2 rounded-full bg-white mt-2"></div>
        {#if i < 4}
          <div class="w-0.5 bg-stone-700 flex-1 min-h-16"></div>
        {/if}
      </div>

      <div class="flex-1 pb-8">
        <p class="text-stone-400 text-sm mb-1">Just now</p>
        <p>Timeline event {i + 1} for {title}</p>
      </div>
    </div>
  {/each}
</div>

<style>
</style>
