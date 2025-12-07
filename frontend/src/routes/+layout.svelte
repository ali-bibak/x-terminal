<script lang="ts">
  import "./layout.css";
  import favicon from "$lib/assets/favicon.svg";
  import Header from "$lib/nav/Header.svelte";

  let { children } = $props();
</script>

<svelte:head>
  <link rel="icon" href={favicon} />
</svelte:head>

<div class="h-full flex flex-col">
  <Header />
  <main class="bg-background text-white px-4 py-2 flex flex-1">
    {@render children()}
  </main>
</div>

<style>
</style>
