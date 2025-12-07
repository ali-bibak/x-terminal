<div class="relative flex items-center gap-2">
  <span class="relative flex h-3 w-3">
    <span
      class="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75"
    ></span>
    <span class="relative inline-flex rounded-full h-3 w-3 bg-white"></span>
  </span>
  <span class="text-sm font-medium">LIVE Updating</span>
</div>

<style>
  @keyframes ping {
    75%,
    100% {
      transform: scale(2);
      opacity: 0;
    }
  }

  .animate-ping {
    animation: ping 1s cubic-bezier(0, 0, 0.2, 1) infinite;
  }
</style>
