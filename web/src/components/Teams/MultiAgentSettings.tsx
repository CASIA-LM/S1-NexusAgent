import {
  Box,
  Button,
  Flex,
  FormControl,
  FormHelperText,
  FormLabel,
  Select,
  Spinner,
  Textarea,
  Text,
  VStack,
  useColorModeValue,
  Avatar,
  Divider,
  Input
} from "@chakra-ui/react";
import { Select as SelectChakraReact } from "chakra-react-select";
import React, { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "react-query";

import { MembersService, type TeamOut } from "@/client";
import { OpenAPI } from "@/client/core/OpenAPI";
import type { MemberOut } from "@/client/models/MemberOut";
import { useModelQuery } from "@/hooks/useModelQuery";
import useCustomToast from "@/hooks/useCustomToast";
import DebugPreview from "@/components/Teams/DebugPreview";
import { IconButton } from "@chakra-ui/react";

// Simple agent option type that works with chakra-react-select
type AgentOption = {
  value: number;
  label: string;
};

interface MultiAgentSettingsProps {
  teamId: number;
}

function buildAgentsUrl() {
  const params = new URLSearchParams({
    workflow: "aip",
    // deploy: "deployed",
    page: "1",
    page_size: "100",
  });
  // 直接使用正确的API基础地址，避免依赖OpenAPI.BASE
  const basePath = "http://localhost:8000/flock";
  const path = `${basePath}/api/v1/deploy/?${params.toString()}`;
  return path;
}
// 使用useEffect处理客户端数据获取，避免在服务端渲染时执行
// Simple agent option type that works with chakra-react-select
interface AgentOptionType {
  value: number;
  label: string;
}

function useAgentTeams() {
  // 使用状态存储智能体列表
  const [agentTeams, setAgentTeams] = useState<AgentOptionType[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isError, setIsError] = useState(false);

  // 在组件挂载时获取数据
  useEffect(() => {
    const fetchAgentTeams = async () => {
      // 确保在客户端执行
      if (typeof window === 'undefined') {
        return;
      }
      
      setIsLoading(true);
      setIsError(false);
      
      try {
        // 获取token - 只在客户端执行
        const token = localStorage.getItem("access_token") || "";
        
        // 发送请求
        const response = await fetch(`${OpenAPI.BASE}/api/v1/teams/?workflow=aip,sequential,workflow_agent&page=1&page_size=100`, {
          method: "GET",
          headers: {
            "Content-Type": "application/json",
            Authorization: token ? `Bearer ${token}` : "",
          },
        });
        
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const body = await response.json();
        
        // Transform data to match our type
        const formattedTeams = (body?.data ?? []).map((item: any) => ({
          value: item.id,
          label: item.name,
        }));
        
        setAgentTeams(formattedTeams);
      } catch (error) {
        console.error("获取智能体失败:", error);
        setIsError(true);
      } finally {
        setIsLoading(false);
      }
    };

    fetchAgentTeams();
  }, []);

  // 返回获取的数据和状态
  return { agentTeams, isLoading, isError };
}

export default function MultiAgentSettings({
  teamId,
}: MultiAgentSettingsProps) {
  // All hooks must be declared at the top level, before any conditional logic
  const toast = useCustomToast();
  const queryClient = useQueryClient();
  const bgColor = useColorModeValue("white", "gray.800");
  
  // Initialize state with default values first
  const [agentName, setAgentName] = useState("多智能体协调中心");
  const [roleContent, setRoleContent] = useState("");
  const [backstory, setBackstory] = useState("");
  const [prompt, setPrompt] = useState("");
  const [selectedAgents, setSelectedAgents] = useState<number[]>([]);
  const [selectedModel, setSelectedModel] = useState("");

  // 自定义函数调用teams/{teamId}/members/detail接口
  const fetchMemberDetail = async (teamId: number): Promise<MemberOut> => {
    // 确保只在客户端执行
    if (typeof window === 'undefined') {
      throw new Error("Cannot fetch member detail on server");
    }
    
    const token = localStorage.getItem("access_token") || "";
    const headers: HeadersInit = {};
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    
    const response = await fetch(`${OpenAPI.BASE}/api/v1/teams/${teamId}/members/detail`, {
      method: "GET",
      headers,
    });
    
    if (!response.ok) {
      throw new Error("Failed to fetch member detail");
    }
    
    return response.json();
  };

  // 创建一个标志来跟踪是否在客户端
  const [isClient, setIsClient] = useState(false);
  
  // 在组件挂载时设置客户端标志
  useEffect(() => {
    setIsClient(true);
  }, []);

  // 使用自定义fetch函数获取成员详情信息，确保只在客户端执行
  const { 
    data: memberDetail,
    isLoading: isLoadingMembers,
    isError: isErrorMembers,
    error: membersError,
  } = useQuery(
    ["multi-agent-member-detail", teamId],
    () => fetchMemberDetail(teamId),
    {
      staleTime: 0,
      enabled: isClient && !!teamId,
    },
  );

  // 直接使用memberDetail作为rootMember
  const rootMember = memberDetail;

  const { data: modelsData, isLoading: isLoadingModels } = useModelQuery();

  // 使用自定义Hook处理客户端数据获取，避免hydration错误
  const { agentTeams, isLoading: isLoadingAgents, isError: isErrorAgents } = useAgentTeams();

  // 从multi_agents字段获取智能体ID列表
  const rootAgentIds = useMemo<number[]>(() => {
    const raw = (rootMember as any)?.multi_agents || (rootMember as any)?.nuliti_agents || [];
    return Array.isArray(raw) ? raw.filter((id: any) => typeof id === "number") : [];
  }, [rootMember]);

  // 当rootMember变化时更新状态
  useEffect(() => {
    if (rootMember) {
      setAgentName(rootMember?.name || "多智能体协调中心");
      setRoleContent(rootMember?.role || "");
      setBackstory(rootMember?.backstory || "");
      setPrompt((rootMember as any)?.prompt || "");
      setSelectedAgents(rootAgentIds);
      setSelectedModel(rootMember?.model ?? "");
    }
  }, [rootMember, rootAgentIds]);

  useEffect(() => {
    if (!selectedModel && modelsData?.data?.length) {
      setSelectedModel(modelsData.data[0].ai_model_name);
    }
  }, [modelsData, selectedModel]);

  const agentOptions = useMemo<AgentOption[]>(() => {
    return (agentTeams ?? []).map((team) => ({
      value: team.value,
      label: team.label,
    }));
  }, [agentTeams]);

  const selectedOptions = useMemo<AgentOption[]>(
    () => agentOptions.filter((option) => selectedAgents.includes(option.value)),
    [agentOptions, selectedAgents],
  );

  const mutation = useMutation({
    mutationFn: () => {
      // 确保只在客户端执行
      if (typeof window === 'undefined') {
        throw new Error("Cannot update member on server");
      }
      
      if (!rootMember?.id) {
        throw new Error("未找到多智能体配置");
      }
      // role是text类型，直接使用roleContent
      const payload = {
        multi_agents: selectedAgents,
        model: selectedModel,
        backstory: backstory,  // 开场白
        prompt: prompt,        // 提示词
        role: roleContent,     // role是text类型，直接使用
        name: agentName        // name可修改
      } as any;
      return MembersService.updateMember({
        teamId,
        id: rootMember.id,
        requestBody: payload as any,
      });
    },
    onSuccess: () => {
      toast("保存成功", "多智能体配置已更新", "success");
      queryClient.invalidateQueries(["multi-agent-member", teamId]);
    },
    onError: (err: any) => {
      const errDetail = err?.body?.detail ?? err?.message ?? "保存失败";
      toast("保存失败", `${errDetail}`, "error");
    },
  });

  // 检查是否有变更
  const hasChanges =
    JSON.stringify(selectedAgents) !== JSON.stringify(rootAgentIds) ||
    backstory !== (rootMember?.backstory ?? "") ||
    prompt !== ((rootMember as any)?.prompt ?? "") ||
    selectedModel !== (rootMember?.model ?? "") ||
    agentName !== (rootMember?.name || "多智能体协调中心") ||
    roleContent !== (rootMember?.role ?? "");

  if (isLoadingMembers || isLoadingAgents || isLoadingModels) {
    return (
      <Flex
        align="center"
        justify="center"
        p={6}
        bg={bgColor}
        borderRadius="xl"
        border="1px solid"
        borderColor="gray.200"
      >
        <Spinner />
      </Flex>
    );
  }

  if (!rootMember) {
    return (
      <Box
        p={4}
        bg={bgColor}
        borderRadius="xl"
        border="1px solid"
        borderColor="gray.200"
      >
        <Text>未找到多智能体成员，请先完成成员配置。</Text>
      </Box>
    );
  }

  if (isErrorAgents || isErrorMembers) {
    const error = (isErrorAgents ? "无法加载可用智能体" : "无法加载成员配置") as string;
    return (
      <Box p={4} bg={bgColor} borderRadius="xl" border="1px solid" borderColor="gray.200">
        <Text color="red.500">{error}</Text>
      </Box>
    );
  }

  return (
    <Box
      p={4}
      bg={bgColor}
      borderRadius="xl"
      border="1px solid"
      borderColor="gray.200"
      boxShadow="sm"
      display="flex"
      flexDirection="column"
      style={{ overflow: 'auto' }}
    >
      <Box 
        flex={1}
        style={{ 
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column' 
        }}
      >
        <Flex justify="flex-end" p={4}>
          <Button
            colorScheme="blue"
            isDisabled={!hasChanges || mutation.isLoading}
            isLoading={mutation.isLoading}
            onClick={() => mutation.mutate()}
          >
            保存配置
          </Button>
        </Flex>
        <div style={{ overflowX: 'auto' }}>
          <Flex gap={6} minWidth="max-content">
            {/* 左侧：角色输入框 */}
            <Box flex={1} style={{ minWidth: '300px', marginBottom: '20px' }}>
              <Text fontSize="lg" fontWeight="600" mb={4}>
                角色配置
              </Text>
              <FormControl>
                <FormLabel>角色内容</FormLabel>
                <Textarea
                  value={roleContent}
                  rows={12}
                  placeholder="输入角色内容"
                  onChange={(event) => setRoleContent(event.target.value)}
                  bg={useColorModeValue("gray.50", "gray.700")}
                />
                <FormHelperText>
                  角色内容以文本格式存储，用于定义智能体的角色定位
                </FormHelperText>
              </FormControl>
              
              <FormControl mt={4}>
                <FormLabel>开场白</FormLabel>
                <Textarea
                  value={backstory}
                  rows={4}
                  placeholder="输入开场白内容"
                  onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setBackstory(e.target.value)}
                />
                <FormHelperText>开场白字段对应后端的backstory</FormHelperText>
              </FormControl>
            </Box>

            {/* 中间：智能体配置 */}
            <Box flex={1} style={{ minWidth: '300px', marginBottom: '20px' }}>
              <Text fontSize="lg" fontWeight="600" mb={4}>
                多智能体协调配置
              </Text>
              
              {/* 智能体基本信息编辑 */}
              <VStack align="stretch" spacing={4} mb={6}>
                <Flex justify="center" mb={4}>
                  <Avatar size="xl">
                    {agentName ? agentName.charAt(0) : "M"}
                  </Avatar>
                </Flex>
                <FormControl>
                  <FormLabel>智能体名称</FormLabel>
                  <Input
                    value={agentName}
                    placeholder="输入智能体名称"
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setAgentName(e.target.value)}
                  />
                  <FormHelperText>名称从详情获取，为空时显示默认名称</FormHelperText>
                </FormControl>
                
                
                
                <FormControl>
                  <FormLabel>提示词</FormLabel>
                  <Textarea
                    value={prompt}
                    rows={4}
                    placeholder="输入提示词内容"
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setPrompt(e.target.value)}
                  />
                  <FormHelperText>提示词字段对应后端的prompt</FormHelperText>
                </FormControl>
                <Divider />
              </VStack>
            
              {/* 原有配置项 */}
              <VStack align="stretch" spacing={4}>
                <FormControl>
                  <FormLabel>执行模型</FormLabel>
                  <Select
                    value={selectedModel}
                    onChange={(event) => setSelectedModel(event.target.value)}
                  >
                    {modelsData?.data?.map((model) => (
                      <option key={model.id} value={model.ai_model_name}>
                        {model.ai_model_name} ({model.provider.provider_name})
                      </option>
                    ))}
                  </Select>
                  <FormHelperText>协调智能体的LLM模型</FormHelperText>
                </FormControl>
                <FormControl>
                  <FormLabel>可用智能体</FormLabel>
                  <SelectChakraReact
                    closeMenuOnSelect={false}
                    isMulti
                    options={agentOptions}
                    placeholder="请选择至少一个已发布智能体"
                    value={selectedOptions}
                    onChange={(value: AgentOption[]) => {
                      const ids = value.map((option: AgentOption) => option.value);
                      setSelectedAgents(ids);
                    }}
                    menuPosition="fixed"
                    menuPlacement="top"
                    menuShouldScrollIntoView={false}
                    maxMenuHeight="250px"
                    menuStyles={{
                      menu: (provided: any) => ({
                        ...provided,
                        borderRadius: "8px",
                        border: "1px solid #e2e8f0",
                        boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.1)",
                        left: "50%",
                        transform: "translateX(-50%)",
                        maxWidth: "300px",
                        width: "90%"
                      }),
                      option: (provided: any) => ({
                        ...provided,
                        padding: "12px 16px",
                        fontSize: "0.875rem"
                      })
                    }}
                  />
                  <FormHelperText>
                    下拉内容来源于已发布的智能体，选中的智能体会被写入 multi_agents。
                  </FormHelperText>
                </FormControl>
                <Button
                  colorScheme="blue"
                  isDisabled={!hasChanges || mutation.isLoading}
                  isLoading={mutation.isLoading}
                  onClick={() => mutation.mutate()}
                >
                  保存配置
                </Button>
              </VStack>
            </Box>

            {/* 右侧：调试Debug Overview */}
            <Box 
              flex={1}
              style={{ minWidth: '300px' }}
              borderRadius="xl" 
              bg="white" 
              border="1px solid" 
              borderColor="gray.100" 
              transition="all 0.2s"
              _hover={{ boxShadow: "sm" }}
            >
              <DebugPreview 
                teamId={Number.parseInt(teamId.toString())} 
                triggerSubmit={() => mutation.mutate()} 
                useDeployButton={true} 
                useApiKeyButton={true} 
              />
            </Box>
          </Flex>
        </div>
      </Box>
    </Box>
  );
}

